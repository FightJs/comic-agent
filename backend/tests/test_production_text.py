import asyncio
import json
import pytest
from types import SimpleNamespace
from backend.store import Store
from backend.production_text import generate, validate_output


def panel(n=1):
    return {'panel':n,'characters':'阿青','scene':'旧院','weather':'雨','time':'夜','shot':'中景','camera':'平视','description':'阿青推开院门。','dialogue':'','sfx':'','note':''}


def fixture(tmp_path):
    store=Store(tmp_path)
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','生产',0,'now','now')")
    return store,{'operation':'range','entry':{'episode':7,'title':'回家','text':'阿青回家'},'episode':7,'panel':1,'batch':1,'instruction':'完整改编','snapshots':[],'skills':[],'frozen':{'records':{},'documents':{},'graph_revision':0,'skills':[]}}


def test_dynamic_panels_strict_identity_and_package_schema():
    assert len(validate_output('range',{'panels':[panel(1),panel(2)]})['panels'])==2
    for bad in [{'panels':[panel(2)]},{'panels':[panel(),panel()]},{'panels':[{**panel(),'episode':8}]},{'panels':[{**panel(),'description':''}]}]:
        with pytest.raises(ValueError):validate_output('range',bad)
    with pytest.raises(ValueError):validate_output('package',{'prompt':'only prose'})


def test_generation_repairs_once_records_raw_and_uses_read_only_tools(tmp_path):
    store,payload=fixture(tmp_path);calls=[]
    class Runtime:
        async def request(self,command,**data):
            calls.append((command,data))
            return {'type':'result','data':{'text':'not json' if len(calls)==1 else json.dumps({'panels':[panel(),panel(2)]}),'usage':None}}
    result=asyncio.run(generate(SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime())),store,'p','task',payload,{'url':'http://fixture','model':'fixture','secret':'not-persisted'}))
    assert len(result['panels'])==2 and len(calls)==2
    assert all(c=='run' and d['tools']==['project_query'] and d['final_only'] for c,d in calls)
    with store.db() as db:
        attempts=[dict(r) for r in db.execute('SELECT * FROM production_attempts ORDER BY attempt')]
    assert [r['status'] for r in attempts]==['invalid','valid']
    assert attempts[0]['raw']=='not json'
    assert 'not-persisted' not in json.dumps(attempts)
    assert calls[0][1]['session_id']!=calls[1][1]['session_id']


def test_invalid_output_does_not_loop_or_publish_partial_results(tmp_path):
    store,payload=fixture(tmp_path);calls=[]
    class Runtime:
        async def request(self,*args,**kw):
            calls.append(kw);return {'type':'result','data':{'text':json.dumps({'panels':[panel(3)]}),'usage':None}}
    with pytest.raises(ValueError):asyncio.run(generate(SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime())),store,'p','task',payload,{'url':'http://fixture','model':'fixture','secret':'fixture'}))
    assert len(calls)==2
    with store.db() as db:assert db.execute('SELECT COUNT(*) FROM records').fetchone()[0]==0


def test_real_pi_reads_frozen_novel_then_creates_two_panels_and_package(tmp_path,monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.graph_documents import import_document
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            messages=body['messages'];last_user=max(i for i,m in enumerate(messages) if m['role']=='user')
            content=messages[last_user]['content']
            prompt=content if isinstance(content,str) else ''.join(v.get('text','') for v in content)
            context=json.loads(prompt.split('固定输入：\n',1)[1].split('\n本次启用流程规则：',1)[0]) if '固定输入：\n' in prompt else None
            has_tool=any(m['role']=='tool' for m in messages[last_user+1:])
            if context is None:
                value={'nodes':[],'edges':[],'summary':'摘要'} if 'TASK:extract' in prompt else {'merges':[],'aliases':[]} if 'TASK:consolidate' in prompt else {'summary':'摘要'}
                delta={'role':'assistant','content':json.dumps(value,ensure_ascii=False)};reason='stop'
            elif not has_tool:
                docid=next(iter(context['frozen_catalog']['documents']))
                delta={'role':'assistant','content':'先核对固定版本原著。','tool_calls':[{'index':0,'id':'read-source','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'source','id':docid})}}]};reason='tool_calls'
            else:
                value={'panels':[panel(),panel(2)]} if context['operation']=='range' else {'scene_prompt':'旧院','content_prompt':'阿青推门','position_prompt':'院门前','shot_prompt':'中景平视','constraints':'保持阿青身份'}
                if context['operation']=='document':value={'title':'骨架','sections':[{'heading':'主线','text':'归乡主线'}]} if context['document_kind']=='skeleton' else {'title':'细纲','entries':[{'episode':1,'title':'归乡','text':'回到旧院','source_range':'第一章'}]}
                delta={'role':'assistant','content':json.dumps(value,ensure_ascii=False)};reason='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for d,r in [(delta,None),({},reason)]:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':d,'finish_reason':r}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'production-sdk-fake-secret')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid=c.post('/api/projects',json={'name':'SDK生产'}).json()['id'];base=f'/api/projects/{pid}'
            with c.app.state.store.db() as db:
                import_document(c.app.state.store,db,pid,'原著.txt','第一章 回家\n阿青推开旧院大门。'.encode())
                db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            outline=c.post(base+'/records',json={'kind':'outline','title':'第一话','content':{'html':'<p>阿青回家。</p>'}}).json()
            c.put(base+'/outline-index/'+outline['id'],json={'outline_version':1,'expected_version':0,'entries':[{'episode':1,'title':'回家','text':'阿青推门回家。'}]})
            response=c.post(base+'/production-jobs',json={'operation':'range','outline_id':outline['id'],'outline_version':1,'index_version':1,'start':1,'end':1,'submission_id':'sdk-range'})
            assert response.status_code==200,response.text
            task=c.get(base+'/tasks').json()[0]
            assert task['status']=='succeeded',task
            panels=c.get(base+'/records?kind=script').json()
            assert len(panels)==2 and all(r['adopted']==0 and r['source']=='ai' for r in panels)
            for r in panels:assert c.post(base+'/candidates/'+r['id']+'/adopt',json={}).status_code==200
            script=c.get(base+'/records/'+panels[0]['id']).json()
            c.post(base+'/production-jobs',json={'operation':'package','refs':[{'id':script['id'],'version':script['version']}],'submission_id':'sdk-package'})
            packages=c.get(base+'/records?kind=package').json()
            assert len(packages)==1 and packages[0]['content']['script_version']==2 and packages[0]['adopted']==0
            receipt=c.get(base+f'/production-jobs/{task["id"]}/attempts').json()
            assert len(receipt)==1 and receipt[0]['status']=='valid' and receipt[0]['tools'][0]['result']['text'].endswith('阿青推开旧院大门。')
            # Read-only reconciliation uses the actual SDK call and exact Python serialization.
            aid=receipt[0]['id'];receipt_url=base+f'/production-jobs/{task["id"]}/attempts/{aid}/tool-receipts'
            count=len(requests)
            checked=c.get(receipt_url)
            assert checked.status_code==200,checked.text
            assert checked.json()['receipts'][0]['state']=='matched'
            assert '阿青推开' not in checked.text and 'session_file' not in checked.text
            other=c.post('/api/projects',json={'name':'其他项目'}).json()['id']
            assert c.get(receipt_url.replace(pid,other)).status_code==404
            checkpoint_path=tmp_path/'agent'/pid/'checkpoints'/(aid+'.json')
            original=checkpoint_path.read_text();cp=json.loads(original)
            tool=cp['tools'][0]
            assert tool.get('session_leaf_id') and tool.get('assistant_leaf_id')
            session_lines=[json.loads(line) for line in (tmp_path/'agent'/cp['session_file']).read_text().splitlines()]
            assistant=next(e for e in session_lines if e.get('id')==tool['assistant_leaf_id'])
            assert any(v.get('id')==tool['id'] for v in assistant['message']['content'])
            tool['status']='registered';tool.pop('result_hash');tool.pop('result_encoding')
            checkpoint_path.write_text(json.dumps(cp))
            before=checkpoint_path.read_bytes()
            missing_ack=c.get(receipt_url)
            assert missing_ack.json()['receipts'][0]['state']=='host_saved_node_unconfirmed'
            assert missing_ack.json()['recovery_available'] is False
            assert checkpoint_path.read_bytes()==before and len(requests)==count
            checkpoint_path.write_text(original)
            assert all([t['function']['name'] for t in r.get('tools',[])]==['project_query'] for r in requests)
            assert len(requests)==4
            # The same actual Pi read-only role produces both document schemas.
            for kind in ('skeleton','outline'):
                body={'operation':'document','document_kind':kind,'submission_id':'sdk-'+kind,'refs':[]}
                if kind=='outline':body.update(refs=[{'id':outline['id'],'version':1}],basis=[{'id':skeleton['id'],'version':2}])
                generated=c.post(base+'/production-jobs',json=body)
                assert generated.status_code==200,generated.text
                jobs=c.get(base+'/tasks').json();job=next(t for t in jobs if t['payload'].get('document_kind')==kind)
                assert job['status']=='succeeded',job
                candidate=c.get(base+'/records/'+job['output_id']).json()
                assert candidate['adopted']==0 and candidate['source']=='ai'
                adopted=c.post(base+'/candidates/'+candidate['id']+'/adopt',json={})
                assert adopted.status_code==200,adopted.text
                if kind=='skeleton':skeleton=adopted.json()
                else:
                    index=c.get(base+'/outline-index/'+outline['id']).json()
                    assert index['content']['outline_version']==2 and index['content']['entries'][0]['source_range']=='第一章'
                    selected=c.put(base+'/graph/outline',json={'record_id':outline['id'],'version':2})
                    assert selected.status_code==200,selected.text
                    import time
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        jobs=c.get(base+'/graph/jobs').json()
                        if jobs and jobs[0]['status'] in ('succeeded','failed'):break
                        time.sleep(.03)
                    assert jobs[0]['status']=='succeeded',jobs
                    graph=c.get(base+'/graph').json()
                    assert graph['outline_id']==outline['id'] and graph['outline_version']==2

            assert len([r for r in requests if r.get('tools')])==8

            other=c.post('/api/projects',json={'name':'另一个'}).json()['id']
            assert c.get(f'/api/projects/{other}/production-jobs/{task["id"]}/attempts').status_code==404
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


def test_novel_directory_is_not_duplicated_into_generation_prompt(tmp_path):
    store,payload=fixture(tmp_path)
    payload['originals']=[{'id':'original','version':1,'title':'长篇','source':'import','content':{'document_id':'novel','parse_version':1,'char_count':60000,'chapters':[{'title':'chapter-title'*40} for _ in range(3000)]}}]
    calls=[]
    class Runtime:
        async def request(self,command,**data):
            calls.append(data)
            return {'type':'result','data':{'text':json.dumps({'panels':[panel()]}),'usage':None}}
    asyncio.run(generate(SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime())),store,'p','task',payload,{'url':'http://fixture','model':'fixture','secret':'fixture'}))
    assert len(calls[0]['prompt'])<180000
    context=json.loads(calls[0]['prompt'].split('固定输入：\n')[1].split('\n本次启用流程规则：')[0])
    assert context['originals'][0]['content']=={'document_id':'novel','parse_version':1,'char_count':60000}


def test_production_duplicate_tool_id_reuses_receipt_and_rejects_changed_input(tmp_path,monkeypatch):
    from fastapi import HTTPException
    from backend.agent_tools import ProjectTools
    store,payload=fixture(tmp_path);calls=[]
    def call(self,name,args):calls.append(args);return {'records':[]}
    monkeypatch.setattr(ProjectTools,'call',call)
    class Runtime:
        async def request(self,command,**data):
            message={'tool_call_id':'stable','name':'project_query','arguments':{'action':'catalog'},'input_hash':'a'*64}
            first=await data['on_tool'](message)
            assert await data['on_tool'](message)==first
            with pytest.raises(HTTPException):await data['on_tool']({**message,'input_hash':'b'*64})
            with pytest.raises(HTTPException):await data['on_tool']({**message,'arguments':{'action':'graph'}})
            return {'type':'result','data':{'text':json.dumps({'panels':[panel()]}),'usage':None}}
    asyncio.run(generate(SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime())),store,'p','task',payload,{'url':'http://fixture','model':'fixture','secret':'fake'}))
    assert len(calls)==1
    with store.db() as db:
        assert db.execute('SELECT COUNT(*) FROM production_tool_calls').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM pi_tool_receipts').fetchone()[0]==1
