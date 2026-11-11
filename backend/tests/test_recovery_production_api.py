import json
from backend.store import dump
from backend import tool_receipts
from backend.tests.test_production_continuation import api_fixture,submit


def test_production_recovery_is_offline_then_explicit_continue(tmp_path,monkeypatch):
    app,client,script,calls,checkpoints=api_fixture(tmp_path,monkeypatch)
    original=app.state.pi_runtime.request
    repairs=[]
    async def request(command,**kw):
        if command=='checkpoint_details':return {'type':'result','data':{'checkpoint':checkpoints[kw['run_id']]}}
        if command=='recover_tools':
            repairs.append(kw['recovery_id']);cp=checkpoints[kw['run_id']]
            cp.update(status='paused',reason='tools_recovered',unresolved_tools=0)
            cp['tools'][0].update(status='received',result_hash=kw['receipts'][0]['result_hash'],result_encoding='host_json')
            return {'type':'result','data':{k:kw[k] for k in ('project_id','session_id','run_id','recovery_id')}|{'checkpoint':{k:v for k,v in cp.items() if k!='tools'}}}
        return await original(command,**kw)
    app.state.pi_runtime.request=request
    with client as c:
        tid=submit(c,script)
        task=c.get('/api/projects/p/tasks').json()[0];aid=task['payload']['production_checkpoint']['attempt_id']
        cp=checkpoints[aid];cp.update(status='failed',unresolved_tools=1)
        cp['tools']=[{'id':'call','name':'project_query','input_hash':'a'*64,'assistant_leaf_id':'leaf','status':'registered'}]
        message={'tool_call_id':'call','name':'project_query','arguments':{},'input_hash':'a'*64};result={'source':'mock','synthetic':True}
        with app.state.store.db() as db:
            db.execute("UPDATE tasks SET status='failed' WHERE id=?",(tid,))
            db.execute("UPDATE production_attempts SET status='error' WHERE id=?",(aid,))
            db.execute('INSERT INTO production_tool_calls VALUES(?,?,?,?,?,?)',('audit',aid,'project_query','{}',dump(result),'t'))
            tool_receipts.save(db,'p','production',aid,message,result)
        path=f'/api/projects/p/production-jobs/{tid}/attempts/{aid}'
        assert c.get(path+'/tool-receipts').json()['recovery_available'] is True
        for body in ({'confirm':False},{'confirm':1},{'confirm':True,'extra':1},{}):assert c.post(path+'/recover-tools',json=body).status_code==422
        assert c.post(path.replace('/projects/p/','/projects/other/')+'/recover-tools',json={'confirm':True}).status_code==404
        before=len(calls)
        response=c.post(path+'/recover-tools',json={'confirm':True});assert response.status_code==200,response.text
        assert response.json()['status']=='paused' and len(calls)==before
        assert c.post(path+'/recover-tools',json={'confirm':True}).status_code==200
        assert len(repairs)==1
        assert c.post(path+'/continue',json={'confirm':True}).status_code==200
        assert c.post(path+'/continue',json={'confirm':True}).status_code==200
        with app.state.store.db() as db:
            assert db.execute('SELECT COUNT(*) FROM production_continuations WHERE parent_id=?',(aid,)).fetchone()[0]==1
            payload=json.loads(db.execute('SELECT payload FROM tasks WHERE id=?',(tid,)).fetchone()[0])
            assert payload['source']=='mock'
