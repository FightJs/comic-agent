import json
import pytest
from backend.tests.test_workflow import setup
from backend.production_text import validate_output


def prepared(tmp_path):
    c,b,add=setup(tmp_path)
    c.post(b+'/text',files={'file':('原著.txt','第一章 回家\n人物归乡后收到来信。'.encode(),'text/plain')})
    calls=[]
    async def request(command,**data):
        calls.append(data)
        context=json.loads(data['prompt'].split('固定输入：\n',1)[1].split('\n本次启用流程规则：',1)[0])
        value={'title':'全书骨架','sections':[{'heading':'核心冲突','text':'以归乡与来信为线索。<script>不可执行</script>'}]} if context.get('document_kind')=='skeleton' else {'title':'分集细纲','entries':[{'episode':1,'title':'归乡','text':'人物回到故乡。','source_range':'第一章'},{'episode':2,'title':'来信','text':'人物收到信件。','source_range':'第一章'}]}
        if context['operation']=='range':
            from backend.tests.test_production_text import panel
            value={'panels':[panel(),panel(2)]}
        return {'type':'result','data':{'text':json.dumps(value,ensure_ascii=False),'usage':None}}
    c.app.state.pi_runtime.request=request
    return c,b,add,calls


def test_document_schemas_reject_empty_duplicate_and_extra_fields():
    for kind,value in [('skeleton',{'title':'骨架','sections':[]}),('outline',{'title':'细纲','entries':[{'episode':1,'title':'甲','text':'甲','source_range':''},{'episode':1,'title':'乙','text':'乙','source_range':''}]}),('skeleton',{'title':'骨架','sections':[{'heading':'冲突','text':'   '}]} )]:
        with pytest.raises(ValueError):validate_output(kind,value)


def test_skeleton_is_escaped_candidate_and_adoption_preserves_original(tmp_path):
    c,b,add,calls=prepared(tmp_path)
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','refs':[],'instruction':'突出核心冲突','submission_id':'skeleton'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0];assert task['status']=='succeeded',task
    candidate=c.get(b+'/records/'+task['output_id']).json()
    assert candidate['source']=='ai' and candidate['adopted']==0
    assert '<script>' not in candidate['content']['html'] and '&lt;script&gt;' in candidate['content']['html']
    assert candidate['content'].get('text') is None
    assert c.post(b+'/candidates/'+candidate['id']+'/adopt',json={}).status_code==200
    adopted=c.get(b+'/records/'+candidate['id']).json()
    assert adopted['version']==2 and adopted['review']=='pending'
    assert c.get(b+'/records?kind=original').json()[0]['source']=='import'
    assert calls[0]['tools']==['project_query']


def test_outline_uses_explicit_skeleton_and_creates_matching_index_only_on_adoption(tmp_path):
    c,b,add,calls=prepared(tmp_path)
    skeleton=add('skeleton',{'html':'<p>固定骨架</p>'})
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'outline','refs':[],'basis':[{'id':skeleton['id'],'version':1}],'submission_id':'outline'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0];assert task['status']=='succeeded',task
    out=c.get(b+'/records/'+task['output_id']).json()
    assert c.get(b+'/outline-index/'+out['id']).json() is None
    assert c.post(b+'/candidates/'+out['id']+'/adopt',json={}).status_code==200
    index=c.get(b+'/outline-index/'+out['id']).json()
    assert index['content']['outline_version']==2
    assert [e['episode'] for e in index['content']['entries']]==[1,2]
    assert index['content']['entries'][0]['source_range']=='第一章'
    assert '固定骨架' in calls[0]['prompt']


def test_document_update_does_not_replace_current_version_until_adopted(tmp_path):
    c,b,add,_=prepared(tmp_path);old=add('skeleton',{'html':'<p>原骨架</p>'})
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','refs':[{'id':old['id'],'version':1}],'submission_id':'rewrite-doc'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0];out=c.get(b+'/records/'+task['output_id']).json()
    assert out['content']['candidate_for']==old['id']
    assert c.get(b+'/records/'+old['id']).json()['version']==1
    c.put(b+'/records/'+old['id'],json={'expected_version':1,'content':{'html':'<p>人工新稿</p>'}})
    assert c.post(b+'/candidates/'+out['id']+'/adopt',json={}).status_code==409


def test_unconfigured_and_legacy_document_generation_do_not_simulate(tmp_path):
    c,b,add=setup(tmp_path,configured=False)
    assert c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','submission_id':'none'}).status_code==422
    assert c.post(b+'/tasks',json={'kind':'skeleton'}).status_code==422
    assert c.get(b+'/tasks').json()==[]


def test_partial_ocr_cannot_be_promoted_by_chapter_correction_or_used_as_whole_book(tmp_path):
    from backend.graph_documents import import_document,chapters_for
    c,b,_,calls=prepared(tmp_path);pid=b.split('/')[-1]
    with c.app.state.store.db() as db:
        text='可读的部分正文。'
        doc=import_document(c.app.state.store,db,pid,'扫描.pdf',b'fixture',parsed=(text,chapters_for(text),['[waiting_ocr] 扫描页未解析'],'unicode'))
        first_job=c.app.state.graph_engine.create_job(db,pid,doc['id'])
    corrected=c.put(b+f'/documents/{doc["id"]}/chapters',json={'parse_version':1,'chapters':[{'title':'可读章节','start':0}]})
    assert corrected.status_code==200,corrected.text
    assert corrected.json()['status']=='waiting_ocr'
    jobs=c.get(b+'/graph/jobs').json()
    assert next(j for j in jobs if j['id']==first_job['id'])['status']=='superseded'
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','submission_id':'partial'})
    assert response.status_code==422 and '解析' in response.text
    assert calls==[]


def test_document_candidate_is_bound_to_selected_novel_and_rejects_source_switch(tmp_path):
    from backend.graph_documents import import_document,chapters_for
    c,b,_,calls=prepared(tmp_path);pid=b.split('/')[-1]
    with c.app.state.store.db() as db:
        # A historical incomplete import must not replace the selected ready novel.
        text='历史不完整正文'
        historical=import_document(c.app.state.store,db,pid,'历史.pdf',b'fixture',parsed=(text,chapters_for(text),['[waiting_ocr] 不完整'],'unicode'))
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','submission_id':'selected'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0]
    assert historical['id'] not in task['payload']['frozen']['documents']
    assert len(task['payload']['originals'])==1
    c.post(b+'/text',files={'file':('新版原著.txt','第一章 新版\n新内容。'.encode(),'text/plain')})
    assert c.post(b+'/candidates/'+task['output_id']+'/adopt',json={}).status_code==409


def test_readable_pdf_without_chapter_titles_does_not_require_ocr(tmp_path):
    import io
    from pypdf import PdfWriter
    from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
    c,b,_=setup(tmp_path)
    writer=PdfWriter();page=writer.add_blank_page(200,100)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 50 Td (Readable novel text without chapter headings.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(content)
    output=io.BytesIO();writer.write(output)
    response=c.post(b+'/documents',files={'file':('readable.pdf',output.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    assert response.json()['status']=='ready'
    assert any('未识别章节' in w for w in response.json()['warnings'])


def test_old_simulated_document_retry_cannot_authorize_new_provider_calls(tmp_path):
    c,b,_,calls=prepared(tmp_path);pid=b.split('/')[-1]
    with c.app.state.store.db() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('legacy-doc',pid,'failed',json.dumps({'kind':'outline'}),None,'模拟失败','t','t'))
    response=c.post(b+'/tasks/legacy-doc/retry')
    assert response.status_code==409 and '重新核对' in response.text
    assert calls==[]


def test_forged_document_candidate_cannot_write_the_read_only_original(tmp_path):
    c,b,add,_=prepared(tmp_path)
    original=c.get(b+'/records?kind=original').json()[0]
    fake=add('skeleton',{'html':'伪造覆盖','candidate_for':original['id'],'input_version':original['version']})
    response=c.post(b+'/candidates/'+fake['id']+'/adopt',json={})
    assert response.status_code==409,response.text
    assert c.get(b+'/records/'+original['id']).json()['version']==original['version']


def test_unselected_skeleton_is_not_a_hidden_generation_reference(tmp_path):
    from backend.agent_tools import ProjectTools
    from fastapi import HTTPException
    c,b,add,_=prepared(tmp_path);skeleton=add('skeleton',{'html':'不应隐式使用的骨架'})
    response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'outline','refs':[],'basis':[],'submission_id':'no-basis'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0];frozen=task['payload']['frozen']
    assert skeleton['id'] not in frozen['records']
    with pytest.raises(HTTPException):ProjectTools(c.app.state.store,b.split('/')[-1],frozen).call('project_query',{'action':'record','id':skeleton['id']})


def test_range_excludes_rejected_and_unadopted_skeletons_from_snapshot_and_tools(tmp_path):
    c,b,add,_=prepared(tmp_path)
    c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','submission_id':'rejected'})
    rejected=c.get(b+'/tasks').json()[0]['output_id']
    assert c.post(b+'/candidates/'+rejected+'/reject',json={}).status_code==200
    kept=add('skeleton',{'html':'当前采用骨架'})
    pending=add('skeleton',{'html':'未采用草稿','creation_candidate':True})
    with c.app.state.store.db() as db:db.execute('UPDATE records SET adopted=0 WHERE id=?',(pending['id'],))
    outline=add('outline',{'html':'<p>当前细纲</p>'})
    c.put(b+'/outline-index/'+outline['id'],json={'outline_version':1,'expected_version':0,'entries':[{'episode':1,'title':'回家','text':'人物回家'}]})
    response=c.post(b+'/production-jobs',json={'operation':'range','outline_id':outline['id'],'outline_version':1,'index_version':1,'start':1,'end':1,'submission_id':'primary-only'})
    assert response.status_code==200,response.text
    task=next(t for t in c.get(b+'/tasks').json() if t['payload']['operation']=='range')
    assert task['status']=='succeeded',task
    assert [r['id'] for r in task['payload']['skeletons']]==[kept['id']]
    assert rejected not in task['payload']['frozen']['records'] and pending['id'] not in task['payload']['frozen']['records']


def test_unadopted_outline_cannot_build_an_index_or_start_downstream_range(tmp_path):
    c,b,_,_=prepared(tmp_path)
    c.post(b+'/production-jobs',json={'operation':'document','document_kind':'outline','submission_id':'pending-outline'})
    out=c.get(b+'/tasks').json()[0]['output_id']
    mapped=c.put(b+'/outline-index/'+out,json={'outline_version':1,'expected_version':0,'entries':[{'episode':1,'title':'甲','text':'甲'}]})
    assert mapped.status_code==409,mapped.text
    response=c.post(b+'/production-jobs',json={'operation':'range','outline_id':out,'outline_version':1,'index_version':1,'start':1,'end':1,'submission_id':'blocked-outline'})
    assert response.status_code==409,response.text


def test_unadopted_outline_cannot_be_selected_for_formal_adaptation_graph(tmp_path):
    c,b,_,_=prepared(tmp_path)
    c.post(b+'/production-jobs',json={'operation':'document','document_kind':'outline','submission_id':'pending-graph'})
    out=c.get(b+'/tasks').json()[0]['output_id']
    response=c.put(b+'/graph/outline',json={'record_id':out,'version':1})
    assert response.status_code==422 and '采用' in response.text,response.text
    assert c.get(b+'/graph/outline').json()['record_id'] is None


def test_adopted_generated_outline_is_compatible_with_graph_episode_mapping(tmp_path):
    c,b,_,_=prepared(tmp_path)
    c.post(b+'/production-jobs',json={'operation':'document','document_kind':'outline','submission_id':'graph-compatible'})
    out=c.get(b+'/tasks').json()[0]['output_id']
    adopted=c.post(b+'/candidates/'+out+'/adopt',json={})
    assert adopted.status_code==200,adopted.text
    response=c.put(b+'/graph/outline',json={'record_id':out,'version':2})
    assert response.status_code==200,response.text
    assert response.json()['record_id']==out
