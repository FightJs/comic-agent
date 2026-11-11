import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app

@pytest.fixture
def paused(tmp_path,monkeypatch,request):
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body);n=len(requests)
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'query'+str(n),'type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]} if n<=20 else {'role':'assistant','content':'已按原固定输入续接完成，尚未采用或生图。'}
            reason='tool_calls' if n<=20 else 'stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for value in [{'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':reason}],**({} if getattr(request,'param',False) and n==5 else {'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}})}]:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',**value})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-continue-key')
    try:
        app=create_app(tmp_path)
        with TestClient(app) as c:
            pid=c.post('/api/projects',json={'name':'续接隔离'}).json()['id'];base=f'/api/projects/{pid}'
            with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            record=c.post(base+'/records',json={'kind':'script','title':'固定脚本','content':{'episode':1,'panel':1,'description':'固定旧稿'}}).json()
            sid=c.post(base+'/agent/sessions',json={'stage':'script','refs':[{'id':record['id'],'version':1}]}).json()['id']
            rid=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'查询这份固定脚本','expected_version':0}).json()['id']
            state=wait(c,base,rid)
            assert state['status']=='paused',state
            assert len(requests)==20
            yield c,base,sid,rid,record,requests
    finally:server.shutdown();server.server_close();thread.join()

def wait(c,base,rid):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        state=c.get(base+f'/agent/runs/{rid}').json()
        if state['status'] not in ('queued','running'):return state
        time.sleep(.02)
    pytest.fail('discussion did not settle')

def test_explicit_continue_preserves_scope_and_is_idempotent(paused):
    c,b,sid,rid,record,requests=paused
    assert c.post(b+f'/agent/sessions/{sid}/messages',json={'message':'不允许绕额度','expected_version':1}).status_code==409
    assert c.put(b+f'/agent/sessions/{sid}/refs',json={'refs':[],'expected_version':1}).status_code==409
    assert c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':False,'expected_version':1}).status_code==422
    body={'confirm':True,'expected_version':1}
    first=c.post(b+f'/agent/runs/{rid}/continue',json=body);assert first.status_code==200,first.text
    child=first.json()['id'];assert child!=rid
    assert c.post(b+f'/agent/runs/{rid}/continue',json=body).json()['id']==child
    final=wait(c,b,child);assert final['status']=='completed',final
    assert len(requests)==21
    assert final['continuation']['parent_run_id']==rid
    assert final['continuation']['known_tokens']==147 and final['continuation']['unknown_runs']==0
    assert final['checkpoint']['parent_run_id']==rid
    parent=c.get(b+f'/agent/runs/{rid}').json();assert parent['status']=='continued'
    assert c.get(b+f'/agent/sessions/{sid}').json()['version']==2
    assert c.get(b+'/records/'+record['id']).json()['version']==1
    assert c.get(b+'/tasks').json()==[]

@pytest.mark.parametrize('change',['record','provider','graph','preferences'])
def test_changed_scope_blocks_paid_continuation(paused,change):
    c,b,sid,rid,record,requests=paused
    if change=='record':assert c.put(b+'/records/'+record['id'],json={'expected_version':1,'content':{'episode':1,'panel':1,'description':'人工新稿'}}).status_code==200
    elif change=='provider':
        with c.app.state.store.db() as db:db.execute("UPDATE settings SET content='{}' WHERE id=1")
    elif change=='preferences':assert c.put(b+'/preferences',json={'expected_revision':0,'text':'新的创作偏好'}).status_code==200
    else:assert c.patch(b+'/graph',json={'expected_revision':0,'operations':[{'op':'add_node','node':{'id':'new','label':'新人物','type':'PERSON'}}]}).status_code==200
    response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1})
    assert response.status_code==409,response.text
    assert len(requests)==20 and len(c.get(b+f'/agent/sessions/{sid}').json()['runs'])==1

def test_cancel_paused_run_allows_new_discussion_and_parent_mock_provenance_is_inherited(paused):
    c,b,sid,rid,record,requests=paused
    with c.app.state.store.db() as db:
        db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',(rid,'synthetic-source','project_query','hash',json.dumps({'source':'mock'}),'then'))
    response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1});assert response.status_code==200,response.text
    child=response.json()['id'];assert wait(c,b,child)['status']=='completed'
    from backend.agent import plan_receipt
    with c.app.state.store.db() as db:assert plan_receipt(c.app.state.store,db,b.split('/')[-1],child,[{'id':record['id'],'version':1}])['source']=='mock'
    assert len(requests)==21

def test_paused_cancel_does_not_dispatch_more_models(paused):
    c,b,sid,rid,record,requests=paused
    assert c.post(b+f'/agent/runs/{rid}/cancel').json()['status']=='cancelled'
    assert c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1}).status_code==409
    assert len(requests)==20

def test_input_change_while_continuation_waits_for_capacity_blocks_dispatch(paused):
    c,b,sid,rid,record,requests=paused
    limits=c.get('/api/runtime/limits').json()
    c.put('/api/runtime/limits',json={'expected_revision':limits['revision'],'limits':{'text':1,'image':1,'vision':1}})
    pool=c.app.state.capacity.pools['text'];c.portal.call(pool.acquire)
    try:
        response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1});assert response.status_code==200,response.text
        child=response.json()['id']
        for _ in range(100):
            if c.get('/api/runtime/limits').json()['usage']['text']['waiting']==1:break
            time.sleep(.01)
        else:pytest.fail('continuation did not queue')
        assert len(requests)==20
        with c.app.state.store.db() as db:c.app.state.store.save(db,b.split('/')[-1],record['id'],1,{'episode':1,'panel':1,'description':'排队期间的新稿'})
    finally:c.portal.call(pool.release)
    assert wait(c,b,child)['status']=='interrupted'
    assert len(requests)==20
    parent=c.get(b+f'/agent/runs/{rid}/checkpoint').json()['checkpoint']
    assert parent['continued_by'] is None

@pytest.mark.parametrize('paused',[True],indirect=True)
def test_continuation_keeps_partial_known_usage_without_claiming_unknown_runs_are_complete(paused):
    c,b,sid,rid,record,requests=paused
    original=c.get(b+f'/agent/runs/{rid}').json()
    assert original['usage'] is None
    assert original['checkpoint']['usage']['totalTokens']==133
    assert not original['checkpoint']['usage_complete']
    response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1});assert response.status_code==200,response.text
    result=wait(c,b,response.json()['id'])
    assert result['status']=='completed'
    assert result['continuation']['known_tokens']==140
    assert result['continuation']['unknown_runs']==1

def test_after_ending_pause_stale_refs_fail_before_creating_a_new_run(paused):
    c,b,sid,rid,record,requests=paused
    assert c.put(b+'/records/'+record['id'],json={'expected_version':1,'content':{'episode':1,'panel':1,'description':'人工新稿'}}).status_code==200
    cancelled=c.post(b+f'/agent/runs/{rid}/cancel').json()
    assert cancelled['status']=='cancelled' and not cancelled['error']
    response=c.post(b+f'/agent/sessions/{sid}/messages',json={'message':'新意见','expected_version':1})
    assert response.status_code==409,response.text
    assert '更新附加资料' in response.json()['detail']
    assert len(c.get(b+f'/agent/sessions/{sid}').json()['runs'])==1
    assert len(requests)==20
    assert c.put(b+f'/agent/sessions/{sid}/refs',json={'expected_version':1,'refs':[{'id':record['id'],'version':2}]}).status_code==200
    sent=c.post(b+f'/agent/sessions/{sid}/messages',json={'message':'使用新稿继续讨论','expected_version':2})
    assert sent.status_code==200,sent.text
    assert wait(c,b,sent.json()['id'])['status']=='completed'
    assert len(requests)==21

@pytest.mark.parametrize('field,value',[('unreturned_models',None),('unresolved_tools',False),('session_saved',1)])
def test_incomplete_checkpoint_summary_does_not_create_a_continuation(paused,monkeypatch,field,value):
    c,b,sid,rid,record,requests=paused
    runtime=c.app.state.pi_runtime
    original=runtime.request
    async def incomplete(command,**kwargs):
        response=await original(command,**kwargs)
        if command=='checkpoint':
            summary=response['data']['checkpoint']
            if value is None:summary.pop(field)
            else:summary[field]=value
        return response
    monkeypatch.setattr(runtime,'request',incomplete)
    response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1})
    assert response.status_code==409,response.text
    assert len(requests)==20
    assert [r['id'] for r in c.get(b+f'/agent/sessions/{sid}').json()['runs']]==[rid]
    assert c.get(b+f'/agent/runs/{rid}').json()['status']=='paused'

@pytest.mark.parametrize('corruption',['missing_responses','unknown_tool_status'])
def test_corrupt_durable_receipts_are_preserved_and_block_public_continuation(paused,corruption):
    c,b,sid,rid,record,requests=paused
    ledger=c.app.state.store.root/'agent'/b.rsplit('/',1)[-1]/'checkpoints'/f'{rid}.json'
    content=json.loads(ledger.read_text())
    if corruption=='missing_responses':content.pop('model_responses')
    else:content['tools'][0]['status']='unknown'
    corrupted=json.dumps(content)
    ledger.write_text(corrupted)
    inspected=c.get(b+f'/agent/runs/{rid}/checkpoint')
    assert inspected.status_code==409,inspected.text
    response=c.post(b+f'/agent/runs/{rid}/continue',json={'confirm':True,'expected_version':1})
    assert response.status_code==409,response.text
    assert len(requests)==20
    assert [r['id'] for r in c.get(b+f'/agent/sessions/{sid}').json()['runs']]==[rid]
    assert c.get(b+f'/agent/runs/{rid}').json()['status']=='paused'
    assert ledger.read_text()==corrupted
