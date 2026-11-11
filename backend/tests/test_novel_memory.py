import json
import pytest
from fastapi import HTTPException
from backend.tests.test_agent_tools import fixture
from backend.agent_tools import ProjectTools,freeze_context
from backend.graph_documents import import_document,save_parse,chapters_for


def novel(store,pid='p',text='第一章 归来\n人物回家。\n第二章 密信\n人物收到信件。'):
    with store.db() as db:return import_document(store,db,pid,'小说.txt',text.encode())


def completed(store,doc,jid='memory-job',status='succeeded',chapters=None,updated='1'):
    chapters=chapters or [('第一章摘要','卷甲'),('第二章摘要','卷甲')]
    with store.db() as db:
        row=db.execute('SELECT project_id FROM documents WHERE id=?',(doc['id'],)).fetchone()
        db.execute('INSERT INTO graph_jobs(id,project_id,kind,status,stage,completed,total,document_id,parse_version,payload,usage,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,row['project_id'],'document',status,'published' if status=='succeeded' else 'extract',len(chapters)+2,len(chapters)+2,doc['id'],doc['parse_version'],json.dumps({'chapters':doc['chapters']}),'{}',updated,updated))
        units=[('extract:0','extract',{'chapter':1,'start':0,'end':doc['char_count']},{'summary':'抽取备注'})]
        units += [(f'chapter_summary:{i}','chapter_summary',{'chapter':min(i+1,len(doc['chapters'])),'title':doc['chapters'][min(i,len(doc['chapters'])-1)]['title']},{'summary':text}) for i,(text,_) in enumerate(chapters)]
        units += [('volume_summary:0','volume_summary',{'volume':'卷甲'},{'summary':'卷甲：人物归乡后追查密信。'})]
        for position,(unit,kind,payload,result) in enumerate(units):
            db.execute('INSERT INTO graph_units VALUES(?,?,?,?,?,?,?,?,?)',(jid,unit,kind,position,json.dumps(payload),'succeeded',1,json.dumps(result,ensure_ascii=False),None))
    return jid


def tool(store,refs=()):
    with store.db() as db:frozen=freeze_context(store,db,'p',refs)
    return ProjectTools(store,'p',frozen),frozen


def test_published_summary_binding_is_immutable_and_distinct_from_original_quotes(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store)
    completed(store,doc)
    tools,frozen=tool(store)
    page=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter','limit':1})
    assert page['status']=='ready' and page['source']=='model_summary'
    assert page['job_id']=='memory-job' and page['parse_version']==1
    assert page['items'][0]['summary']=='第一章摘要' and page['next_start']==1
    assert page['items'][0]['locator']['scope']=='chapter' and 'quote' not in page['items'][0]
    completed(store,doc,'new-memory',chapters=[('新版摘要','卷甲')],updated='2')
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter'})['job_id']=='memory-job'
    newer,_=tool(store)
    assert newer.call('project_query',{'action':'novel_summary','id':doc['id']})['job_id']=='new-memory'
    assert frozen['novel_memory'][doc['id']]['job_id']=='memory-job'


def test_not_ready_and_old_snapshots_never_silently_gain_new_memory(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store)
    tools,_=tool(store)
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_ready'
    completed(store,doc)
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_ready'
    with store.db() as db:frozen=freeze_context(store,db,'p')
    frozen.pop('novel_memory')
    assert ProjectTools(store,'p',frozen).call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_frozen'


def test_summary_is_parse_scoped_and_cannot_cross_projects_or_job_ids(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store);foreign=novel(store,'other');completed(store,doc);completed(store,foreign,'foreign-job')
    with store.db() as db:save_parse(store,db,'p',doc['id'],'新版原著',chapters_for('新版原著'),[])
    tools,_=tool(store)
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_ready'
    with pytest.raises(HTTPException):tools.call('project_query',{'action':'novel_summary','id':foreign['id']})
    with pytest.raises(HTTPException):tools.call('project_query',{'action':'novel_summary','id':'foreign-job'})


def test_long_notes_are_bounded_and_full_unit_can_be_read_by_text_range(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store)
    completed(store,doc,chapters=[('甲'*30000+'唯一线索','卷甲')])
    tools,_=tool(store)
    page=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter','limit':50})
    item=page['items'][0]
    assert len(item['summary'])<=4000 and item['truncated'] is True
    detail=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'unit:'+item['unit_id'],'start':29990})
    assert detail['summary'].endswith('唯一线索') and detail['text_start']==29990 and detail['text_end']==30004
    search=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'search:唯一线索'})
    assert search['total']==1 and search['items'][0]['unit_id']==item['unit_id']
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'search:不存在'})['items']==[]


def test_catalog_explains_available_memory_and_mock_origin_is_not_laundered(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store);completed(store,doc)
    with store.db() as db:
        rid=db.execute('SELECT record_id FROM documents WHERE id=?',(doc['id'],)).fetchone()[0]
        db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(rid,))
    tools,_=tool(store)
    catalog=tools.call('project_query',{'action':'catalog'})
    assert catalog['novel_memory'][doc['id']]['job_id']=='memory-job'
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['source']=='mock'


@pytest.mark.parametrize('state',['running','failed','cancelled','superseded'])
def test_partial_or_failed_jobs_are_not_whole_book_memory(tmp_path,state):
    store,_,_,_=fixture(tmp_path);doc=novel(store);completed(store,doc,status=state)
    tools,_=tool(store)
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_ready'


def test_middle_pages_and_multiple_parts_of_one_chapter_are_never_silently_dropped(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store)
    completed(store,doc,chapters=[(f'模型笔记单元{i}','卷甲') for i in range(125)])
    tools,_=tool(store)
    seen=[];start=0
    while start is not None:
        page=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter','start':start,'limit':50})
        assert len(page['items'])<=20
        seen.extend(i['unit_id'] for i in page['items']);start=page['next_start']
    assert len(seen)==len(set(seen))==125
    assert 'chapter_summary:63' in seen
    with store.db() as db:assert db.execute('SELECT COUNT(*) FROM records WHERE project_id=?',('p',)).fetchone()[0]==2


def test_legacy_parse_reference_can_read_its_own_old_summary_and_incomplete_ocr_cannot(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store);completed(store,doc)
    with store.db() as db:
        rid=db.execute('SELECT record_id FROM documents WHERE id=?',(doc['id'],)).fetchone()[0]
        save_parse(store,db,'p',doc['id'],'新版正文',chapters_for('新版正文'),[])
    tools,_=tool(store,[{'id':rid,'version':1}])
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id']})['job_id']=='memory-job'
    with store.db() as db:db.execute('UPDATE document_parses SET warnings=? WHERE document_id=? AND version=1',(json.dumps(['[waiting_ocr] 未完成']),doc['id']))
    newer,_=tool(store,[{'id':rid,'version':1}])
    assert newer.call('project_query',{'action':'novel_summary','id':doc['id']})['status']=='not_ready'


def test_real_sdk_builds_then_reads_published_memory_and_checks_the_original(tmp_path,monkeypatch):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.app as module
    requests=[];state={}
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            messages=body['messages'];last=max(i for i,m in enumerate(messages) if m['role']=='user')
            raw=messages[last]['content'];prompt=raw if isinstance(raw,str) else ''.join(c.get('text','') for c in raw)
            if not body.get('tools'):
                result={'nodes':[],'edges':[],'summary':'抽取笔记'} if 'TASK:extract' in prompt else {'merges':[],'aliases':[]} if 'TASK:consolidate' in prompt else {'summary':'卷章笔记：人物归乡后收到密信。'}
                delta={'role':'assistant','content':json.dumps(result,ensure_ascii=False)};reason='stop'
            else:
                receipts=[m for m in messages[last+1:] if m['role']=='tool']
                if len(receipts)<2:
                    args={'action':'novel_summary','query':'chapter:1'} if not receipts else {'action':'source','id':state['did']}
                    delta={'role':'assistant','tool_calls':[{'index':0,'id':'memory-'+str(len(receipts)),'type':'function','function':{'name':'project_query','arguments':json.dumps(args)}}]};reason='tool_calls'
                else:delta={'role':'assistant','content':'【隔离SDK答复】模型笔记与第一章原文已核对，未声称通读未查部分。'};reason='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for value,finish in [(delta,None),({},reason)]:
                chunk={'id':'memory-fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':value,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'memory-fixture-private-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid=c.post('/api/projects',json={'name':'摘要SDK验收'}).json()['id'];base=f'/api/projects/{pid}'
            c.put('/api/settings',json={'purpose':'text','url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'})
            doc=c.post(base+'/documents',files={'file':('小说.txt','第一章 归来\n人物归乡后收到密信。'.encode(),'text/plain')}).json();state['did']=doc['id']
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                jobs=c.get(base+'/graph/jobs').json()
                if jobs[0]['status'] in ('succeeded','failed'):break
                time.sleep(.03)
            assert jobs[0]['status']=='succeeded',jobs
            original=c.get(base+'/records?kind=original').json()[0]
            session=c.post(base+'/agent/sessions',json={'stage':'memory','refs':[{'id':original['id'],'version':original['version']}]}).json()
            run=c.post(base+f'/agent/sessions/{session["id"]}/messages',json={'message':'查阅卷章笔记，并核对第一章原文','expected_version':0}).json()
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                result=c.get(base+f'/agent/runs/{run["id"]}').json()
                if result['status'] not in ('queued','running'):break
                time.sleep(.03)
            assert result['status']=='completed',result
            assert '模型笔记与第一章原文已核对' in result['reply']
            assert result['novel_memory'][doc['id']]['job_id']==jobs[0]['id']
            assert result['preferred_document']=={'id':doc['id'],'parse_version':1}
            with c.app.state.store.db() as db:
                receipts=[json.loads(r['result']) for r in db.execute('SELECT result FROM agent_tool_calls WHERE run_id=? ORDER BY rowid',(run['id'],))]
            assert receipts[0]['source']=='model_summary' and receipts[0]['items'][0]['summary'].startswith('卷章笔记')
            assert receipts[1]['source']=='import' and '人物归乡后收到密信。' in receipts[1]['text']
            assert 'model_summary' in json.dumps(requests[-1],ensure_ascii=False)
            assert '本次固定原著摘要任务' in json.dumps(requests[-1],ensure_ascii=False)
            assert c.get(base+'/tasks').json()==[]
            assert c.get(base+'/records/'+original['id']).json()['version']==1
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


def test_specific_chapter_and_volume_queries_use_parse_identity_not_page_offsets(tmp_path):
    store,_,_,_=fixture(tmp_path);doc=novel(store);completed(store,doc)
    tools,_=tool(store)
    chapter=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter:2'})
    assert chapter['total']==1 and chapter['items'][0]['summary']=='第二章摘要'
    assert chapter['items'][0]['locator']['chapter']==2
    volume=tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'volume:卷甲'})
    assert volume['total']==1 and volume['items'][0]['locator']['volume']=='卷甲'
    assert tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':'chapter:999'})['items']==[]
    for query in ('chapter:0','chapter:bad','volume:','search: '):
        with pytest.raises(HTTPException):tools.call('project_query',{'action':'novel_summary','id':doc['id'],'query':query})


def test_default_memory_follows_frozen_current_source_or_explicit_original_reference(tmp_path):
    store,_,_,_=fixture(tmp_path);old=novel(store);new=novel(store,text='第一章 新版\n新版密信。')
    completed(store,old,'old-memory');completed(store,new,'new-memory')
    with store.db() as db:
        db.execute('INSERT INTO graph_source VALUES(?,?,?,?)',('p',new['id'],1,1))
        old_rid=db.execute('SELECT record_id FROM documents WHERE id=?',(old['id'],)).fetchone()[0]
        new_rid=db.execute('SELECT record_id FROM documents WHERE id=?',(new['id'],)).fetchone()[0]
    tools,frozen=tool(store)
    assert tools.call('project_query',{'action':'novel_summary'})['job_id']=='new-memory'
    assert frozen['preferred_document']['id']==new['id']
    explicit,_=tool(store,[{'id':old_rid,'version':1}])
    assert explicit.call('project_query',{'action':'novel_summary'})['job_id']=='old-memory'
    with store.db() as db:db.execute('UPDATE graph_source SET document_id=?,generation=2 WHERE project_id=?',(old['id'],'p'))
    assert tools.call('project_query',{'action':'novel_summary'})['job_id']=='new-memory'
    multiple,_=tool(store,[{'id':old_rid,'version':1},{'id':new_rid,'version':1}])
    with pytest.raises(HTTPException):multiple.call('project_query',{'action':'novel_summary'})
