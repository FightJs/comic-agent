import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app


def install_graph_transport(app, transport):
    """Legacy graph fixtures now stub only the constrained runtime boundary."""
    import httpx
    original=app.state.pi_runtime.request
    async def request(command, **payload):
        if command!='complete': return await original(command,**payload)
        async with httpx.AsyncClient(transport=transport) as client:
            response=await client.post('https://fixture.invalid/chat/completions',json={'messages':[{'role':'system','content':payload['system']},{'role':'user','content':payload['prompt']}]})
            response.raise_for_status(); envelope=response.json()
        u=envelope.get('usage')
        return {'type':'result','data':{'text':envelope['choices'][0]['message']['content'],'usage':{'input':u['prompt_tokens'],'output':u['completion_tokens']} if u else None}}
    app.state.pi_runtime.request=request


def project(c):
    return c.post('/api/projects', json={'name': '图谱测试'}).json()['id']


def upload(c,p,text='第一章 起\n阿青走进旧院。\n第二章 终\n阿青遇见老人。',name='novel.txt'):
    r=c.post(f'/api/projects/{p}/documents',files={'file':(name,text.encode(),'text/plain')})
    assert r.status_code==200,r.text
    return r.json()


def patch(c,p,operations,rev=0):
    return c.patch(f'/api/projects/{p}/graph',json={'expected_revision':rev,'operations':operations})


def test_documents_unicode_versions_and_no_large_record_duplication(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c); d=upload(c,p,'第一章 起\n😀阿青\n第二章 终\n阿青归来。')
        assert d['parse_version']==1 and d['chapter_count']==2
        assert d['char_count']==len('第一章 起\n😀阿青\n第二章 终\n阿青归来。')
        endpoint=f'/api/projects/{p}/documents/{d["id"]}'
        assert c.get(endpoint+'/text?start=6&end=7').json()['text']=='😀'
        records=c.get(f'/api/projects/{p}/records').json()
        assert records[0]['kind']=='original' and 'text' not in records[0]['content']
        changed=c.put(endpoint+'/chapters',json={'parse_version':1,'chapters':[{'title':'全书','start':0}]}).json()
        assert changed['parse_version']==2
        assert c.get(endpoint+'/text?parse_version=1&chapter=2').json()['title']=='第二章 终'
        jobs=c.get(f'/api/projects/{p}/graph/jobs').json()
        assert any(j['status']=='waiting_config' for j in jobs)
        q=project(c)
        assert c.get(f'/api/projects/{q}/documents/{d["id"]}/text').status_code==404


def test_graph_manual_locks_revision_history_merge_restore_and_isolation(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        g=patch(c,p,[{'op':'add_node','node':{'id':'a','label':'阿青','type':'PERSON','aliases':['青儿']}},{'op':'add_node','node':{'id':'b','label':'老人','type':'PERSON'}},{'op':'add_edge','edge':{'id':'e','source':'a','target':'b','relation':'师徒','inferred':True,'reason':'对话暗示'}}]).json()
        assert g['revision']==1 and g['nodes'][0]['locked_fields']
        assert patch(c,p,[],0).status_code==409
        g=patch(c,p,[{'op':'update_node','node_id':'a','patch':{'summary':'手动身份'}}],1).json()
        assert 'summary' in g['nodes'][0]['locked_fields']
        g=patch(c,p,[{'op':'merge_nodes','node_ids':['a','b'],'target_id':'a'}],2).json()
        assert len(g['nodes'])==1 and {'a','b'}<=set(g['nodes'][0]['original_ids'])
        assert c.get(f'/api/projects/{p}/graph/history').json()[0]['revision']==3
        g=c.post(f'/api/projects/{p}/graph/restore',json={'expected_revision':3,'revision':1}).json()
        assert g['revision']==4 and len(g['nodes'])==2
        q=project(c)
        assert c.get(f'/api/projects/{q}/graph/entities/a').status_code==404


def test_time_filter_removes_future_aliases_attributes_states_and_evidence(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        # Unknown temporal provenance is hidden when a cutoff is selected.
        patch(c,p,[{'op':'add_node','node':{'id':'a','label':'阿青','type':'PERSON','known_from':1,'summary':'后来的身份','aliases':['王女'],'attributes':{'秘密':'王女'},'states':[{'id':'s','label':'女王','known_from':4}]}},{'op':'add_node','node':{'id':'b','label':'老人','type':'PERSON','known_from':3}}])
        g=c.get(f'/api/projects/{p}/graph?at=1').json()
        assert len(g['nodes'])==1
        assert g['nodes'][0]['summary']=='' and g['nodes'][0]['aliases']==[] and g['nodes'][0]['attributes']=={} and g['nodes'][0]['states']==[]


def test_real_provider_atomic_publish_and_invalid_evidence_fail_without_empty_graph(tmp_path,monkeypatch):
    import httpx
    import backend.app as app_module
    monkeypatch.setattr(app_module.vault,'get_password',lambda *a:'test-key')
    app=create_app(tmp_path); calls=[]
    def transport(req):
        import json
        body=json.loads(req.content); prompt=body['messages'][-1]['content']; calls.append(prompt)
        if 'TASK:extract' in prompt:
            result={'nodes':[{'id':'a','label':'阿青','type':'PERSON','aliases':[], 'summary':'走进旧院','evidence':[{'start':6,'end':8,'quote':'阿青'}]}], 'edges':[], 'events':[]}
        elif 'TASK:consolidate' in prompt:
            result={'merges':[],'aliases':[]}
        else: result={'summary':'本章摘要'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}],'usage':{'prompt_tokens':2,'completion_tokens':3}})
    install_graph_transport(app,httpx.MockTransport(transport))
    with TestClient(app) as c:
        p=project(c)
        c.put('/api/settings',json={'purpose':'text','url':'https://standin.invalid/v1','model':'test-model'})
        d=upload(c,p,'第一章 起\n阿青走进旧院。')
        deadline=time.time()+5
        while time.time()<deadline:
            jobs=c.get(f'/api/projects/{p}/graph/jobs').json()
            if jobs[0]['status'] in ('succeeded','failed'): break
            time.sleep(.03)
        assert jobs[0]['status']=='succeeded',jobs
        g=c.get(f'/api/projects/{p}/graph?layer=original').json()
        assert len(g['nodes'])==1 and g['nodes'][0]['evidence'][0]['document_id']==d['id']
        assert jobs[0]['usage']['input_tokens']>=6 and any('TASK:consolidate' in x for x in calls)
        assert c.get(f'/api/projects/{p}/graph').json()['nodes'] # initial original fallback


def wait_job(c,p,terminal=('succeeded','failed','superseded'),timeout=5):
    end=time.time()+timeout
    while time.time()<end:
        values=c.get(f'/api/projects/{p}/graph/jobs').json()
        if values and values[0]['status'] in terminal: return values[0]
        time.sleep(.02)
    pytest.fail(f'Job timeout: {values}')


def provider_app(tmp_path,monkeypatch,handler):
    import httpx
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'local-test-only')
    app=create_app(tmp_path)
    def transport(req):
        import json
        prompt=json.loads(req.content)['messages'][-1]['content']; result=handler(prompt)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]})
    install_graph_transport(app,httpx.MockTransport(transport))
    return app


def test_bad_quote_retries_three_and_does_not_publish(tmp_path,monkeypatch):
    calls=[]
    def answer(prompt):
        calls.append(prompt)
        return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'start':6,'end':8,'quote':'错字'}]}],'edges':[]}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c); c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test','purpose':'text'})
        upload(c,p,'第一章 起\n阿青出门。')
        j=wait_job(c,p)
        assert j['status']=='failed' and len(calls)==3 and len(j['issues'])==3
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_pause_cancel_restart_manual_resume_and_five_million_characters(tmp_path):
    app=create_app(tmp_path)
    text='第一章 起\n'+'山'*5_000_000
    with TestClient(app) as c:
        p=project(c); d=upload(c,p,text)
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        assert j['total']>1700 and d['char_count']==len(text)
        assert c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/pause').json()['status']=='paused'
        assert c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/cancel').json()['status']=='cancelled'
        assert c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/retry').json()['status']=='waiting_config'
        with app.state.store.db() as db: db.execute("UPDATE graph_jobs SET status='running' WHERE id=?",(j['id'],))
    with TestClient(create_app(tmp_path)) as c:
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        assert j['status']=='interrupted' and j['total']>1700
        assert c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/resume').json()['status']=='waiting_config'
        assert c.get(f'/api/projects/{p}/documents/{d["id"]}/text?start=4999990&end=5000000').json()['text']=='山'*10


def test_outline_sync_preserves_identity_and_empty_clears_without_fallback(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:
            import json
            original_ids=[]
            if 'ORIGINAL_IDENTITIES:' in prompt:
                identities=json.loads(prompt.split('ORIGINAL_IDENTITIES:')[1]); original_ids=[identities[0]['id']] if identities else []
            return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','original_ids':original_ids,'summary':None if original_ids else '原著描述','aliases':None if original_ids else [],'attributes':{} if original_ids else {'appearance':'青衣'},'evidence':[{'start':6,'end':8,'quote':'阿青'}]}],'edges':[],'summary':'章节摘要'}
        if 'consolidate' in prompt: return {'merges':[],'aliases':[]}
        return {'summary':'总结'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c); c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青出门。'); assert wait_job(c,p)['status']=='succeeded'
        original=c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes'][0]
        r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'确定细纲','content':{'text':'第1话 起\n阿青出门。'}}).json()
        result=c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1})
        assert result.status_code==200,result.text
        time.sleep(.05); assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json()
        assert g['outline_id']==r['id'] and g['nodes'][0]['id']==original['id']
        assert g['nodes'][0]['summary']=='原著描述' and g['nodes'][0]['attributes']=={}
        c.put(f'/api/projects/{p}/records/{r["id"]}',json={'expected_version':1,'content':{'text':'第1话 起\n阿青归来。'}})
        with app.state.store.db() as db:
            selection=db.execute('SELECT * FROM graph_outline WHERE project_id=?',(p,)).fetchone()
            assert selection['version']==2 and 8<selection['due']-time.time()<=10
        clear=c.put(f'/api/projects/{p}/graph/outline',json={'record_id':None,'version':None})
        assert clear.status_code==200
        assert c.get(f'/api/projects/{p}/graph').json()['nodes']==[]
        assert c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes']


def test_invalid_manual_evidence_rejected(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c); d=upload(c,p)
        value={'id':'a','label':'青','type':'PERSON','evidence':[{'document_id':d['id'],'parse_version':1,'chapter':1,'start':0,'end':2,'quote':'不存在'}]}
        assert patch(c,p,[{'op':'add_node','node':value}]).status_code==422
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_asset_confirmation_checks_exact_style_review_and_only_writes_visual_fields(tmp_path):
    from backend.tests.test_api import png
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        patch(c,p,[{'op':'add_node','node':{'id':'a','label':'阿青','type':'PERSON','states':[{'id':'s','label':'日常','attributes':{'personality':'谨慎'}}]}}])
        draft=c.post(f'/api/projects/{p}/graph/assets/draft',json={'entity_id':'a','state_id':'s'}).json()
        assert draft['content']['entity_id']=='a'
        style=c.post(f'/api/projects/{p}/images',files={'file':('风格.png',png(),'image/png')},data={'kind':'style'}).json()
        c.post(f'/api/projects/{p}/records/{style["id"]}/reviews',json={'version':1,'decision':'approved','note':'确认'})
        c.post(f'/api/projects/{p}/style-selection',json={'record_id':style['id'],'version':1})
        asset=c.post(f'/api/projects/{p}/images',files={'file':('青.png',png(),'image/png')},data={'kind':'asset'}).json()
        asset=c.put(f'/api/projects/{p}/records/{asset["id"]}',json={'expected_version':1,'content':{**asset['content'],'visual_fields':{'hair':'白发','personality':'凶恶','motivation':'复仇'},'entity_id':'a','state_id':'s'}}).json()
        endpoint=f'/api/projects/{p}/graph/assets/confirm'; body={'asset_id':asset['id'],'version':2,'entity_id':'a','state_id':'s','role':'main'}
        assert c.post(endpoint,json=body).status_code==409
        c.post(f'/api/projects/{p}/records/{asset["id"]}/reviews',json={'version':2,'decision':'approved','note':'确认'})
        c.post(f'/api/projects/{p}/records/{asset["id"]}/adopt',json={'version':2})
        result=c.post(endpoint,json=body)
        assert result.status_code==200,result.text
        state=result.json()['nodes'][0]['states'][0]
        assert state['attributes']=={'personality':'谨慎','hair':'白发'}
        assert state['assets'][0]['valid'] is True
        c.post(f'/api/projects/{p}/records/{asset["id"]}/reviews',json={'version':2,'decision':'changes','note':'需改'})
        state=c.get(f'/api/projects/{p}/graph').json()['nodes'][0]['states'][0]
        assert state['assets'][0]['valid'] is False and state['assets'][0]['reason']


def test_legacy_txt_import_creates_document_and_compact_original_record(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        r=c.post(f'/api/projects/{p}/text',files={'file':('old.txt','第一章 起\n阿青。'.encode('gb18030'),'text/plain')}).json()
        docs=c.get(f'/api/projects/{p}/documents').json()
        assert len(docs)==1 and r['content']['document_id']==docs[0]['id']
        assert 'text' not in c.get(f'/api/projects/{p}/records').json()[0]['content']
        assert c.get(f'/api/projects/{p}/graph/jobs').json()[0]['status']=='waiting_config'


def test_summary_failure_keeps_previous_revision_visible(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt: return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'start':6,'end':8,'quote':'阿青'}]}],'edges':[],'summary':'摘要'}
        return {'bad':'provider failed summary structure'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c); patch(c,p,[{'op':'add_node','node':{'id':'manual','label':'人工人物','type':'PERSON'}}])
        c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青。'); j=wait_job(c,p)
        assert j['status']=='failed' and j['stage']=='chapter_summary'
        g=c.get(f'/api/projects/{p}/graph').json()
        assert g['revision']==1 and g['nodes'][0]['id']=='manual'


def test_temporal_projection_keeps_previous_attribute_value_and_unknown_outline_alias_hidden(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:
            start=int(prompt.split('start=')[1].split(',')[0]); chapter=int(prompt.split('Chapter/episode ')[1].split('.')[0])
            quote='阿青'; offset=start+6
            return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','identity_key':'confirmed-aqing','summary':'女王身份' if chapter==2 else '旅行者','attributes':{'clothing':'王袍' if chapter==2 else '青衣'},'aliases':[], 'evidence':[{'start':offset,'end':offset+2,'quote':quote}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:
            import json
            entities=json.loads(prompt.split('\n',1)[1])['entities']
            return {'merges':[{'node_ids':[n['id'] for n in entities],'target_id':entities[0]['id'],'reason':'原文明确同一主角','evidence':entities[-1]['evidence']}] if len(entities)==2 else [],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青出门。\n第二章 终\n阿青登基。'); assert wait_job(c,p)['status']=='succeeded'
        all_nodes=c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes']
        assert all_nodes[0]['attributes']['clothing']=='王袍'
        early=c.get(f'/api/projects/{p}/graph?layer=original&at=1').json()['nodes'][0]
        assert early['attributes']=={'clothing':'青衣'} and early['summary']=='旅行者'


def test_manual_locks_and_suppression_survive_original_reextract(tmp_path,monkeypatch):
    summary=['初稿']
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','summary':summary[0],'evidence':[{'start':6,'end':8,'quote':'阿青'}]},{'id':'b','label':'旧院','type':'LOCATION','evidence':[{'start':9,'end':11,'quote':'旧院'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        d=upload(c,p,'第一章 起\n阿青到旧院。'); assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json(); a,b=g['nodes']
        g=patch(c,p,[{'op':'update_node','node_id':a['id'],'patch':{'summary':''}},{'op':'delete_node','node_id':b['id']}],g['revision']).json()
        summary[0]='再抽取描述'; c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'new-model'})
        c.post(f'/api/projects/{p}/documents/{d["id"]}/reparse'); assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json()
        assert len(g['nodes'])==1 and g['nodes'][0]['summary']==''
        assert any(x['field']=='summary' and x['manual']=='' for x in g['conflicts'])


def test_legacy_persisted_record_migrates_into_documents(tmp_path):
    from backend.store import Store,uid,now
    store=Store(tmp_path)
    with store.db() as db:
        pid=uid(); stamp=now();db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(pid,'旧项目',0,stamp,stamp))
        r=store.add(db,pid,'original','旧小说.txt',{'text':'第一章 起\n阿青。','encoding':'utf-8','chapters':[]},'import')
    with TestClient(create_app(tmp_path)) as c:
        d=c.get(f'/api/projects/{pid}/documents').json()
        assert len(d)==1
        assert c.get(f'/api/projects/{pid}/records/{r["id"]}').json()['content']['document_id']==d[0]['id']
        assert c.get(f'/api/projects/{pid}/documents/{d[0]["id"]}/text').json()['text']=='第一章 起\n阿青。'


def test_evidence_endpoint_resolves_original_and_outline_references(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c); d=upload(c,p,'第一章 起\n阿青走进旧院。')
        evidence={'document_id':d['id'],'parse_version':1,'chapter':1,'start':6,'end':8,'quote':'阿青'}
        result=c.post(f'/api/projects/{p}/graph/evidence',json=evidence)
        assert result.status_code==200 and '阿青走进旧院' in result.json()['text']
        r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'text':'第1话 起\n阿青出门。'}}).json()
        evidence={'document_id':'','parse_version':0,'chapter':1,'start':6,'end':8,'quote':'阿青','source_kind':'outline','record_id':r['id'],'record_version':1}
        result=c.post(f'/api/projects/{p}/graph/evidence',json=evidence)
        assert result.status_code==200 and result.json()['title']=='细纲'
        evidence['quote']='错字'
        assert c.post(f'/api/projects/{p}/graph/evidence',json=evidence).status_code==422


def test_rerun_succeeded_source_creates_job_with_cache(tmp_path,monkeypatch):
    calls=[]
    def answer(prompt):
        calls.append(prompt)
        if 'TASK:extract' in prompt:return {'nodes':[],'edges':[],'summary':'风景章节'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'风景摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        d=upload(c,p,'第一章 起\n青山。'); old=wait_job(c,p); count=len(calls)
        new=c.post(f'/api/projects/{p}/graph/jobs',json={'document_id':d['id']}).json()
        assert new['id']!=old['id']
        assert wait_job(c,p)['status']=='succeeded' and len(calls)==count


def test_scan_pdf_uses_configured_mineru_http_and_keeps_warning(tmp_path,monkeypatch):
    import httpx
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'local-parse-test-key')
    app=create_app(tmp_path)
    app.state.graph_parse_transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'results':{'scan':{'md_content':'第一章 起\n阿青走进旧院。','content_list':[{'type':'text','text':'第一章 起\n阿青走进旧院。','page_idx':0}]}}}))
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'purpose':'parse','url':'https://mineru-standin.invalid','model':'pipeline'})
        import io
        from pypdf import PdfWriter
        pdf=io.BytesIO(); writer=PdfWriter(); writer.add_blank_page(100,100);writer.write(pdf)
        d=c.post(f'/api/projects/{p}/documents',files={'file':('scan.pdf',pdf.getvalue(),'application/pdf')})
        assert d.status_code==200,d.text
        assert wait_job(c,p,terminal=('waiting_config','failed'))['status']=='waiting_config'
        doc=c.get(f'/api/projects/{p}/documents').json()[0]
        assert doc['char_count']>8 and any('MinerU' in w for w in doc['warnings'])


def test_cloud_mineru_pending_document_poll_upload_and_all_pages(tmp_path,monkeypatch):
    import httpx,io,zipfile,json
    import backend.app as module
    from pypdf import PdfWriter
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'cloud-test-key')
    app=create_app(tmp_path); calls=[]
    output=io.BytesIO()
    blocks=[{'type':'text','text':'第一章 起','page_idx':0},{'type':'text','text':'阿青进入旧院。','page_idx':1}]
    with zipfile.ZipFile(output,'w') as archive: archive.writestr('novel_content_list.json',json.dumps(blocks,ensure_ascii=False))
    def handler(req):
        calls.append((req.method,str(req.url)))
        if req.url.path.endswith('/file-urls/batch'):
            assert req.headers['authorization']=='Bearer cloud-test-key'
            return httpx.Response(200,json={'code':0,'data':{'batch_id':'test-batch','file_urls':['https://signed.invalid/upload']}})
        if req.url.host=='signed.invalid':
            assert 'authorization' not in req.headers
            return httpx.Response(200)
        if '/extract-results/batch/' in req.url.path:return httpx.Response(200,json={'code':0,'data':{'extract_result':[{'state':'done','full_zip_url':'https://output.invalid/full.zip'}]}})
        return httpx.Response(200,content=output.getvalue())
    app.state.graph_parse_transport=httpx.MockTransport(handler)
    pdf=io.BytesIO(); writer=PdfWriter();writer.add_blank_page(100,100);writer.add_blank_page(100,100);writer.write(pdf)
    with TestClient(app) as c:
        p=project(c)
        d=c.post(f'/api/projects/{p}/documents',files={'file':('scan.pdf',pdf.getvalue(),'application/pdf')})
        assert d.status_code==200,d.text
        assert d.json()['status']=='waiting_ocr'
        assert c.get(f'/api/projects/{p}/graph/jobs').json()[0]['status']=='waiting_ocr'
        c.put('/api/settings',json={'purpose':'parse','url':'https://mineru.invalid/api/v4','model':'pipeline'})
        j=wait_job(c,p,terminal=('waiting_config','failed'),timeout=5)
        assert j['status']=='waiting_config' # extraction is queued after complete OCR; text model intentionally unset
        docs=c.get(f'/api/projects/{p}/documents').json(); assert docs[0]['status']=='ready'
        text=c.get(f'/api/projects/{p}/documents/{d.json()["id"]}/text').json()['text']
        assert '第一章 起' in text and '阿青进入旧院。' in text
        assert any(method=='PUT' for method,url in calls)


def test_document_search_uses_codepoints_and_reports_capped_results(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c); d=upload(c,p,'第一章 起\n😀阿青\n第二章 终\n'+'阿青。'*1001)
        route=f'/api/projects/{p}/documents/{d["id"]}/search'
        result=c.get(route,params={'q':'阿青'}).json()
        assert result['matches'][0]=={'start':7,'end':9,'chapter':1}
        assert result['total']==1002 and result['truncated'] is True and len(result['matches'])==1000
        assert c.get(route,params={'q':''}).status_code==422


def test_new_unconfirmed_asset_version_keeps_confirmed_old_reference_valid(tmp_path):
    from backend.tests.test_api import png
    with TestClient(create_app(tmp_path)) as c:
        p=project(c);patch(c,p,[{'op':'add_node','node':{'id':'a','label':'青','type':'PERSON','states':[{'id':'s','label':'日常'}]}}])
        style=c.post(f'/api/projects/{p}/images',files={'file':('style.png',png(),'image/png')},data={'kind':'style'}).json()
        c.post(f'/api/projects/{p}/records/{style["id"]}/reviews',json={'version':1,'decision':'approved','note':'确定'})
        c.post(f'/api/projects/{p}/style-selection',json={'record_id':style['id'],'version':1})
        asset=c.post(f'/api/projects/{p}/images',files={'file':('asset.png',png(),'image/png')},data={'kind':'asset'}).json()
        c.post(f'/api/projects/{p}/records/{asset["id"]}/reviews',json={'version':1,'decision':'approved','note':'确定'})
        body={'asset_id':asset['id'],'version':1,'entity_id':'a','state_id':'s','role':'main'}
        assert c.post(f'/api/projects/{p}/graph/assets/confirm',json=body).status_code==200
        c.put(f'/api/projects/{p}/records/{asset["id"]}',json={'expected_version':1,'content':{**asset['content'],'description':'待审核新稿'}})
        ref=c.get(f'/api/projects/{p}/graph').json()['nodes'][0]['states'][0]['assets'][0]
        assert ref['version']==1 and ref['valid'] is True
        assert c.post(f'/api/projects/{p}/graph/assets/confirm',json=body).status_code==200
        g=c.get(f'/api/projects/{p}/graph').json()
        g=patch(c,p,[{'op':'add_node','node':{'id':'b','label':'白','type':'PERSON'}}],g['revision']).json()
        g=patch(c,p,[{'op':'merge_nodes','node_ids':['a','b'],'target_id':'a'}],g['revision']).json()
        assert g['nodes'][0]['states'][0]['assets'][0]['valid'] is False
        assert c.post(f'/api/projects/{p}/graph/assets/confirm',json=body).status_code==200


def test_manual_late_rename_cannot_leak_via_timeline_context(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        patch(c,p,[{'op':'add_node','node':{'id':'a','label':'青','type':'PERSON','known_from':1}}])
        patch(c,p,[{'op':'update_node','node_id':'a','patch':{'label':'隐秘女王'}}],1)
        g=c.get(f'/api/projects/{p}/graph?at=1').json()
        assert all(n['label']!='隐秘女王' for n in g['nodes'])
        response=c.get(f'/api/projects/{p}/graph/context?entity_id=a&at=1')
        assert '隐秘女王' not in response.text


def test_cloud_ocr_missing_page_cannot_publish_partial_source(tmp_path,monkeypatch):
    import io,httpx,json,zipfile
    from pypdf import PdfWriter
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'fake-parse-key')
    app=create_app(tmp_path); zipped=io.BytesIO()
    with zipfile.ZipFile(zipped,'w') as archive: archive.writestr('content_list.json',json.dumps([{'type':'text','text':'第一章 起\n缺页之前的正文。','page_idx':0}]))
    def transport(req):
        if req.url.path.endswith('/file-urls/batch'):return httpx.Response(200,json={'code':0,'data':{'batch_id':'x','file_urls':['https://signed.invalid/upload']}})
        if req.method=='PUT':return httpx.Response(200)
        if 'extract-results' in req.url.path:return httpx.Response(200,json={'code':0,'data':{'extract_result':[{'state':'done','full_zip_url':'https://out.invalid/full.zip'}]}})
        return httpx.Response(200,content=zipped.getvalue())
    app.state.graph_parse_transport=httpx.MockTransport(transport)
    pdf=io.BytesIO();w=PdfWriter();w.add_blank_page(100,100);w.add_blank_page(100,100);w.write(pdf)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'purpose':'parse','url':'https://mineru.invalid/api/v4'})
        d=c.post(f'/api/projects/{p}/documents',files={'file':('mixed.pdf',pdf.getvalue(),'application/pdf')}).json()
        j=wait_job(c,p); assert j['status']=='failed'
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0
        assert c.get(f'/api/projects/{p}/documents').json()[0]['status']=='waiting_ocr'


def test_outline_retains_unused_original_and_manual_edges_with_locks(tmp_path,monkeypatch):
    def answer(prompt):
        import json
        if 'TASK:extract' in prompt:
            ids=json.loads(prompt.split('ORIGINAL_IDENTITIES:')[1]); original_ids=[ids[0]['id']] if ids else []
            nodes=[{'id':'a','label':'阿青','type':'PERSON','original_ids':original_ids,'evidence':[{'start':6,'end':8,'quote':'阿青'}]}]
            if not ids:nodes.append({'id':'b','label':'旧院','type':'LOCATION','evidence':[{'start':9,'end':11,'quote':'旧院'}]})
            return {'nodes':nodes,'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青到旧院。');assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json(); a,b=g['nodes']
        patch(c,p,[{'op':'add_edge','edge':{'id':'manual-e','source':a['id'],'target':b['id'],'relation':'用户设定'}}],g['revision'])
        r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'text':'第1话 起\n阿青。'}}).json()
        c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1});assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json()
        unused=next(n for n in g['nodes'] if n['id']==b['id'])
        assert unused['in_adaptation'] is False
        assert any(e['id']=='manual-e' and e['relation']=='用户设定' for e in g['edges'])


def test_latest_import_fences_old_document_even_when_old_job_finishes_late(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c); a=upload(c,p,'第一章 起\n旧书。'); b=upload(c,p,'第一章 起\n新书。')
        with c.app.state.store.db() as db:
            engine=c.app.state.graph_engine
            old=db.execute('SELECT * FROM graph_jobs WHERE document_id=?',(a['id'],)).fetchone()
            db.execute("UPDATE graph_jobs SET status='running' WHERE id=?",(old['id'],))
            engine.finish(db,old,[])
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0
        assert c.get(f'/api/projects/{p}/documents/{a["id"]}/text').status_code==200


def test_same_name_without_identity_key_remains_distinct_until_evidence_merge(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:
            start=int(prompt.split('start=')[1].split(',')[0])+6
            return {'nodes':[{'id':'mr','label':'王先生','type':'PERSON','evidence':[{'start':start,'end':start+3,'quote':'王先生'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n王先生住在城东。\n第二章 终\n王先生住在城西。');assert wait_job(c,p)['status']=='succeeded'
        assert len(c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes'])==2


def test_local_mineru_without_page_coverage_fails_instead_of_dropping_pages(tmp_path,monkeypatch):
    import io,httpx
    from pypdf import PdfWriter
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'fake-local-parse-key')
    app=create_app(tmp_path);app.state.graph_parse_transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'results':{'scan':{'md_content':'只有一页的文字。'}}}))
    pdf=io.BytesIO();w=PdfWriter();w.add_blank_page(100,100);w.add_blank_page(100,100);w.write(pdf)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'purpose':'parse','url':'https://local.invalid/file_parse'})
        c.post(f'/api/projects/{p}/documents',files={'file':('mixed.pdf',pdf.getvalue(),'application/pdf')})
        j=wait_job(c,p,terminal=('waiting_config','failed'))
        assert j['status']=='failed' and c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_original_rerun_preserves_manually_added_edge(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'start':6,'end':8,'quote':'阿青'}]},{'id':'b','label':'旧院','type':'LOCATION','evidence':[{'start':9,'end':11,'quote':'旧院'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        d=upload(c,p,'第一章 起\n阿青到旧院。');assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json();a,b=g['nodes']
        patch(c,p,[{'op':'add_edge','edge':{'id':'manual-e','source':a['id'],'target':b['id'],'relation':'人工设定'}}],g['revision'])
        c.post(f'/api/projects/{p}/graph/jobs',json={'document_id':d['id']});assert wait_job(c,p)['status']=='succeeded'
        assert c.get(f'/api/projects/{p}/graph').json()['edges'][0]['id']=='manual-e'


def test_explicit_cleared_adaptation_stays_empty_after_source_rerun(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'start':6,'end':8,'quote':'阿青'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        d=upload(c,p,'第一章 起\n阿青。');assert wait_job(c,p)['status']=='succeeded'
        c.put(f'/api/projects/{p}/graph/outline',json={'record_id':None,'version':None})
        c.post(f'/api/projects/{p}/graph/jobs',json={'document_id':d['id']});assert wait_job(c,p)['status']=='succeeded'
        assert c.get(f'/api/projects/{p}/graph').json()['nodes']==[]
        assert len(c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes'])==1


def test_provider_unique_quote_is_located_when_offset_hints_missing_or_wrong(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'start':99999,'end':100001,'quote':'阿青'}]},{'id':'b','label':'旧院','type':'LOCATION','evidence':[{'quote':'旧院'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n😀阿青到旧院。');assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph?layer=original').json()
        assert {n['label']:n['evidence'][0]['start'] for n in g['nodes']}=={'阿青':7,'旧院':10}


def test_provider_repeated_quote_without_offsets_or_context_is_rejected(tmp_path,monkeypatch):
    def answer(prompt):
        return {'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'quote':'阿青'}]}],'edges':[],'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青看见镜中的阿青。');assert wait_job(c,p)['status']=='failed'
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_cancelled_inflight_provider_usage_is_counted_without_publish(tmp_path,monkeypatch):
    import asyncio,httpx,json,threading
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'fake-text-key')
    started=threading.Event(); release=threading.Event()
    class GatedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            started.set();await asyncio.to_thread(release.wait,3)
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'nodes':[],'edges':[],'summary':'风景摘要'})}}],'usage':{'prompt_tokens':7,'completion_tokens':9}})
    app=create_app(tmp_path);install_graph_transport(app,GatedTransport())
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n风景。'); assert started.wait(3)
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/cancel'); release.set()
        end=time.time()+3
        while time.time()<end:
            j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
            if j['usage']['input_tokens']:break
            time.sleep(.02)
        assert j['status']=='cancelled' and j['usage']=={'input_tokens':7,'output_tokens':9}
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_invalid_consolidation_fails_job_instead_of_stalling(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'a','label':'青','type':'PERSON','evidence':[{'quote':'阿青'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[{'node_ids':['missing','also-missing'],'target_id':'missing','reason':'模型错误','evidence':[]}],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n阿青。');time.sleep(1)
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        assert j['status']=='failed'
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==0


def test_model_identity_key_does_not_merge_homonyms_without_consolidation_evidence(tmp_path,monkeypatch):
    def answer(prompt):
        if 'TASK:extract' in prompt:return {'nodes':[{'id':'mr','identity_key':'wang','label':'王先生','type':'PERSON','evidence':[{'quote':'王先生'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n王先生住城东。\n第二章 终\n王先生住城西。');assert wait_job(c,p)['status']=='succeeded'
        assert len(c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes'])==2


def test_invalid_json_after_cancel_cannot_replace_terminal_status(tmp_path,monkeypatch):
    import asyncio,httpx,threading
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'fake-text-key')
    started=threading.Event(); release=threading.Event()
    class GatedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            started.set();await asyncio.to_thread(release.wait,3)
            return httpx.Response(200,json={'choices':[{'message':{'content':'invalid JSON'}}],'usage':{'prompt_tokens':7,'completion_tokens':9}})
    app=create_app(tmp_path);install_graph_transport(app,GatedTransport())
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,'第一章 起\n风景。'); assert started.wait(3)
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        with app.state.store.db() as db:db.execute('UPDATE graph_units SET attempts=3 WHERE job_id=?',(j['id'],))
        c.post(f'/api/projects/{p}/graph/jobs/{j["id"]}/cancel');release.set();time.sleep(.1)
        j=c.get(f'/api/projects/{p}/graph/jobs').json()[0]
        assert j['status']=='cancelled' and j['usage']['input_tokens']==7


def test_unknown_pdf_pagecount_fails_before_remote_ocr(tmp_path,monkeypatch):
    import httpx
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'fake-parse-key')
    calls=[]
    app=create_app(tmp_path)
    def transport(req):
        calls.append(req)
        return httpx.Response(200,json={'results':{'scan':{'content_list':[{'type':'text','text':'未知页数原文。','page_idx':0}]}}})
    app.state.graph_parse_transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'purpose':'parse','url':'https://local.invalid/file_parse'})
        c.post(f'/api/projects/{p}/documents',files={'file':('bad.pdf',b'%PDF-not-valid','application/pdf')})
        j=wait_job(c,p,terminal=('waiting_config','failed'))
        assert j['status']=='failed' and calls==[]


def test_restore_rejects_removing_later_asset_identity_dependency(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c);patch(c,p,[{'op':'add_node','node':{'id':'a','label':'青','type':'PERSON','states':[{'id':'sa','label':'日常'}]}}])
        patch(c,p,[{'op':'add_node','node':{'id':'b','label':'白','type':'PERSON','states':[{'id':'sb','label':'日常'}]}}],1)
        r=c.post(f'/api/projects/{p}/records',json={'kind':'asset','title':'白的已关联草稿','content':{'entity_id':'b','state_id':'sb'}})
        assert r.status_code==200
        restored=c.post(f'/api/projects/{p}/graph/restore',json={'expected_revision':2,'revision':1})
        assert restored.status_code==409 and '资产' in restored.json()['detail']
        assert c.get(f'/api/projects/{p}/graph').json()['revision']==2


def test_unlock_can_release_relation_field_protection(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c)
        patch(c,p,[{'op':'add_node','node':{'id':'a','label':'青','type':'PERSON'}},{'op':'add_node','node':{'id':'b','label':'白','type':'PERSON'}},{'op':'add_edge','edge':{'id':'e','source':'a','target':'b','relation':'相识'}}])
        r=patch(c,p,[{'op':'unlock','edge_id':'e','fields':['relation']}],1)
        assert r.status_code==200,r.text
        assert 'relation' not in r.json()['edges'][0]['locked_fields']


def test_explicit_asset_rebind_moves_reference_without_mutating_image_version(tmp_path):
    from backend.tests.test_api import png
    with TestClient(create_app(tmp_path)) as c:
        p=project(c);patch(c,p,[{'op':'add_node','node':{'id':'a','label':'青','type':'PERSON','states':[{'id':'sa','label':'日常'}]}},{'op':'add_node','node':{'id':'b','label':'白','type':'PERSON','states':[{'id':'sb','label':'晚装'}]}}])
        style=c.post(f'/api/projects/{p}/images',files={'file':('style.png',png(),'image/png')},data={'kind':'style'}).json()
        c.post(f'/api/projects/{p}/records/{style["id"]}/reviews',json={'version':1,'decision':'approved','note':'确定'})
        c.post(f'/api/projects/{p}/style-selection',json={'record_id':style['id'],'version':1})
        asset=c.post(f'/api/projects/{p}/images',files={'file':('asset.png',png(),'image/png')},data={'kind':'asset'}).json()
        asset=c.put(f'/api/projects/{p}/records/{asset["id"]}',json={'expected_version':1,'content':{**asset['content'],'entity_id':'a','state_id':'sa'}}).json()
        c.post(f'/api/projects/{p}/records/{asset["id"]}/adopt',json={'version':2})
        c.post(f'/api/projects/{p}/records/{asset["id"]}/reviews',json={'version':2,'decision':'approved','note':'确定'})
        body={'asset_id':asset['id'],'version':2,'entity_id':'a','state_id':'sa','role':'main'}
        assert c.post(f'/api/projects/{p}/graph/assets/confirm',json=body).status_code==200
        body.update(entity_id='b',state_id='sb')
        assert c.post(f'/api/projects/{p}/graph/assets/confirm',json=body).status_code==409
        body['rebind']=True
        result=c.post(f'/api/projects/{p}/graph/assets/confirm',json=body)
        assert result.status_code==200,result.text
        nodes={n['id']:n for n in result.json()['nodes']}
        assert nodes['a']['states'][0]['assets']==[] and nodes['b']['states'][0]['assets'][0]['valid'] is True
        current=c.get(f'/api/projects/{p}/records/{asset["id"]}').json()
        assert current['version']==2 and current['content']['entity_id']=='a'


def test_identity_merge_keeps_two_people_and_their_facts_separate_before_reveal(tmp_path,monkeypatch):
    def answer(prompt):
        import json
        if 'TASK:extract' in prompt:
            chapter=int(prompt.split('Chapter/episode ')[1].split('.')[0]); name='甲' if chapter==1 else '乙'
            nodes=[{'id':'person','label':name,'type':'PERSON','summary':'青衣旅人' if chapter==1 else '王宫密使','attributes':{'身份':'旅人' if chapter==1 else '密使'},'states':[{'label':'日常','attributes':{'服装':'青衣' if chapter==1 else '王袍'},'evidence':[{'quote':name}]}],'evidence':[{'quote':name}]}] if chapter<3 else []
            if chapter==2:nodes.append({'id':'place','label':'王宫','type':'LOCATION','evidence':[{'quote':'王宫'}]})
            edges=[{'source':'person','target':'place','relation':'效忠','evidence':[{'quote':'乙效忠王宫'}]}] if chapter==2 else []
            return {'nodes':nodes,'edges':edges,'summary':'第三章揭露身份' if chapter==3 else '人物登场'}
        if 'consolidate' in prompt:
            entities=json.loads(prompt.split('\n',1)[1])['entities']; people=[n for n in entities if n['type']=='PERSON']
            if len(people)==2:
                a=next(n for n in people if n['label']=='甲'); b=next(n for n in people if n['label']=='乙')
                basis={**b['evidence'][0],'chapter':3,'start':30,'end':37,'quote':'甲与乙是同一人'}
                # Actual reveal evidence is bound by test source offsets below.
                return {'merges':[{'node_ids':[a['id'],b['id']],'target_id':a['id'],'reason':'第三章明确揭示','evidence':[basis]}],'aliases':[]}
            return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    text='第一章 起\n甲行旅。\n第二章 终\n乙效忠王宫。\n第三章 明\n甲与乙是同一人。'
    reveal=text.index('甲与乙是同一人')
    # Keep quoted offsets real and independent of guessed character counts.
    def corrected(prompt):
        result=answer(prompt)
        for merge in result.get('merges',[]):merge['evidence'][0].update(start=reveal,end=reveal+7)
        return result
    app=provider_app(tmp_path,monkeypatch,corrected)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,text);assert wait_job(c,p)['status']=='succeeded'
        early=c.get(f'/api/projects/{p}/graph?layer=original&at=2').json(); people={n['label']:n for n in early['nodes'] if n['type']=='PERSON'}
        assert set(people)=={'甲','乙'}
        assert people['甲']['attributes']['身份']=='旅人' and people['甲']['summary']=='青衣旅人'
        assert '乙' not in people['甲']['aliases'] and all(e['quote']!='乙' for e in people['甲']['evidence'])
        assert people['甲']['states'][0]['attributes']['服装']=='青衣'
        assert people['乙']['attributes']['身份']=='密使'
        assert early['edges'][0]['source']==people['乙']['id']
        late=c.get(f'/api/projects/{p}/graph?layer=original&at=3').json()
        assert len([n for n in late['nodes'] if n['type']=='PERSON'])==1


def test_same_label_state_does_not_move_earlier_on_late_identity_merge(tmp_path,monkeypatch):
    text='第一章 起\n甲登场。\n第二章 终\n乙登场。\n第三章 装\n乙换上日常装。\n第四章 明\n甲乙同人。'
    def answer(prompt):
        import json
        if 'TASK:extract' in prompt:
            chapter=int(prompt.split('Chapter/episode ')[1].split('.')[0])
            if chapter==4:return {'nodes':[],'edges':[],'summary':'揭露身份'}
            name='甲' if chapter==1 else '乙'
            return {'nodes':[{'id':'p','label':name,'type':'PERSON','states':[{'label':'日常','attributes':{},'evidence':[{'quote':name}]}] if chapter in (1,3) else [],'evidence':[{'quote':name}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:
            entities=json.loads(prompt.split('\n',1)[1])['entities']
            if len(entities)<3:return {'merges':[],'aliases':[]}
            a=next(n for n in entities if n['label']=='甲'); bs=sorted((n for n in entities if n['label']=='乙'),key=lambda n:n['evidence'][0]['chapter']); b,c=bs
            basis3={**c['evidence'][0],'quote':'乙换上日常装','start':text.index('乙换上日常装'),'end':text.index('乙换上日常装')+6,'chapter':3}
            basis4={**a['evidence'][0],'quote':'甲乙同人','start':text.index('甲乙同人'),'end':text.index('甲乙同人')+4,'chapter':4}
            return {'merges':[{'node_ids':[b['id'],c['id']],'target_id':b['id'],'reason':'第三章同一乙','evidence':[basis3]},{'node_ids':[a['id'],b['id']],'target_id':b['id'],'reason':'第四章同人','evidence':[basis4]}],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'test'})
        upload(c,p,text);assert wait_job(c,p)['status']=='succeeded'
        early=c.get(f'/api/projects/{p}/graph?layer=original&at=2').json()
        b=next(n for n in early['nodes'] if n['label']=='乙')
        assert all(s['label']!='日常' for s in b['states'])


def test_outline_evidence_rejects_wrong_episode_for_valid_quote(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p=project(c);text='第1话 起\n旧院。\n第2话 终\n阿青出门。'
        r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'text':text}}).json();offset=text.index('阿青')
        evidence={'document_id':'','parse_version':0,'chapter':1,'start':offset,'end':offset+2,'quote':'阿青','source_kind':'outline','record_id':r['id'],'record_version':1}
        assert c.post(f'/api/projects/{p}/graph/evidence',json=evidence).status_code==422
        evidence['chapter']=2
        assert c.post(f'/api/projects/{p}/graph/evidence',json=evidence).status_code==200


@pytest.mark.parametrize('layer',['original','outline'])
def test_locked_automatic_node_survives_omission_but_unedited_node_does_not(tmp_path,monkeypatch,layer):
    omit=[False]
    def answer(prompt):
        if 'TASK:extract' in prompt:
            nodes=[] if omit[0] else [{'id':'a','label':'阿青','type':'PERSON','evidence':[{'quote':'阿青'}]},{'id':'b','label':'旧院','type':'LOCATION','evidence':[{'quote':'旧院'}]}]
            return {'nodes':nodes,'edges':[],'summary':'未再提及人物' if omit[0] else '人物登场'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'first-model'})
        if layer=='original': d=upload(c,p,'第一章 起\n阿青到旧院。')
        else:
            r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'text':'第1话 起\n阿青到旧院。'}}).json()
            c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1})
        assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json();a,b=g['nodes']
        patch(c,p,[{'op':'update_node','node_id':a['id'],'patch':{'label':'人工命名的阿青'}}],g['revision'])
        omit[0]=True;c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'second-model'})
        if layer=='original':c.post(f'/api/projects/{p}/graph/jobs',json={'document_id':d['id']})
        else:c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1})
        assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json()
        assert [n['id'] for n in g['nodes']]==[a['id']]
        assert g['nodes'][0]['label']=='人工命名的阿青'
        conflict=next(v for v in g['conflicts'] if v['target_id']==a['id'] and v['field']=='__presence')
        assert conflict['incoming'] is None
        g=patch(c,p,[{'op':'add_edge','edge':{'id':'self-edge','source':a['id'],'target':a['id'],'relation':'人工记忆'}}],g['revision']).json()
        resolved=patch(c,p,[{'op':'resolve_conflict','conflict_id':conflict['id'],'choice':'incoming'}],g['revision']).json()
        assert resolved['nodes']==[] and resolved['edges']==[]


@pytest.mark.parametrize('layer',['original','outline'])
def test_reappeared_node_invalidates_old_absence_conflict_only_for_current_source(tmp_path,monkeypatch,layer):
    omit=[False]
    def answer(prompt):
        if prompt.startswith('TASK:extract'):
            return {'nodes':[] if omit[0] else [{'id':'a','label':'阿青','type':'PERSON','evidence':[{'quote':'阿青'}]}],'edges':[],'summary':'摘要'}
        if 'consolidate' in prompt:return {'merges':[],'aliases':[]}
        return {'summary':'摘要'}
    app=provider_app(tmp_path,monkeypatch,answer)
    with TestClient(app) as c:
        p=project(c);c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':'first-model'})
        if layer=='original':d=upload(c,p,'第一章 起\n阿青。')
        else:
            r=c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'text':'第1话 起\n阿青。'}}).json()
            c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1})
        assert wait_job(c,p)['status']=='succeeded'
        g=c.get(f'/api/projects/{p}/graph').json();a=g['nodes'][0]
        patch(c,p,[{'op':'update_node','node_id':a['id'],'patch':{'label':'人工阿青'}}],g['revision'])
        def rerun(model):
            c.put('/api/settings',json={'url':'https://standin.invalid/v1','model':model})
            if layer=='original':c.post(f'/api/projects/{p}/graph/jobs',json={'document_id':d['id']})
            else:c.put(f'/api/projects/{p}/graph/outline',json={'record_id':r['id'],'version':1})
            assert wait_job(c,p)['status']=='succeeded'
        omit[0]=True;rerun('second-model')
        g=c.get(f'/api/projects/{p}/graph').json();old=next(v for v in g['conflicts'] if v['field']=='__presence')
        from backend import graph_store as gs
        with app.state.store.db() as db:
            revision,state=gs.load(app.state.store,db,p)
            state['conflicts'].append({'id':'other-source-presence','target_id':'unrelated','field':'__presence','manual':'其他来源保留','incoming':None,'source':'outline' if layer=='original' else 'original','evidence':[]})
            gs.publish(app.state.store,db,p,state,'跨来源冲突夹具')
        omit[0]=False;rerun('third-model')
        g=c.get(f'/api/projects/{p}/graph').json()
        assert all(v['id']!=old['id'] for v in g['conflicts'])
        assert any(v['id']=='other-source-presence' for v in g['conflicts'])
        assert g['nodes'][0]['label']=='人工阿青' and 'label' in g['nodes'][0]['locked_fields']
        response=patch(c,p,[{'op':'resolve_conflict','conflict_id':old['id'],'choice':'incoming'}],g['revision'])
        assert response.status_code in (409,422)
        current=c.get(f'/api/projects/{p}/graph').json()
        assert current['revision']==g['revision'] and current['nodes'][0]['id']==a['id']


@pytest.mark.parametrize('with_usage',[False,True])
def test_graph_runs_through_real_pi_single_call_without_tools_or_sessions(tmp_path,monkeypatch,with_usage):
    import json,threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            prompt=body['messages'][-1]['content']
            result={'nodes':[{'id':'a','label':'阿青','type':'PERSON','evidence':[{'quote':'阿青'}]}],'edges':[],'summary':'摘要'} if 'TASK:extract' in prompt else {'merges':[],'aliases':[]} if 'TASK:consolidate' in prompt else {'summary':'摘要'}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for delta,reason in [({'role':'assistant','content':json.dumps(result,ensure_ascii=False)},None),({},'stop')]:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':reason}]}
                if with_usage and reason: chunk['usage']={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'graph-sdk-fixture-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            p=project(c);c.put('/api/settings',json={'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','api':'openai-completions'})
            upload(c,p,'第一章 起\n阿青回家。')
            job=wait_job(c,p,timeout=15)
            assert job['status']=='succeeded',job
            if with_usage: assert job['usage']=={'input_tokens':2*len(requests),'output_tokens':3*len(requests)}
            else: assert job['usage']['unknown'] is True
            assert c.get(f'/api/projects/{p}/graph?layer=original').json()['nodes'][0]['label']=='阿青'
            assert requests and all(not r.get('tools') and len(r['messages'])==2 for r in requests)
            assert not list((tmp_path/'agent').rglob('*.jsonl'))
    finally:server.shutdown();server.server_close();thread.join(timeout=3)
