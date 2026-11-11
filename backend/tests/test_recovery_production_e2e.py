"""Real SDK production interruption after host commit; recovery never replays tools."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from fastapi.testclient import TestClient
from backend.app import create_app
import backend.app as module


def test_real_production_host_receipt_recovery_then_explicit_continue(tmp_path,monkeypatch):
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if len(requests)==1:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'production-saved','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]};reason='tool_calls'
            else:delta={'role':'assistant','content':json.dumps({'patch':{'description':'真实SDK恢复后的完整脚本'}})};reason='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for change,finish in ((delta,None),({},reason)):
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':change,'finish_reason':finish}]}
                if finish:chunk['usage']={'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'synthetic-production-recovery-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            app=c.app;runtime=app.state.pi_runtime;original=runtime._tool;saved=[]
            async def drop_ack(message,on_tool):
                saved.append(await on_tool(message));runtime.process.kill()
            monkeypatch.setattr(runtime,'_tool',drop_ack)
            pid=c.post('/api/projects',json={'name':'生产真实故障恢复'}).json()['id'];base=f'/api/projects/{pid}'
            with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            script=c.post(base+'/records',json={'kind':'script','title':'第一格','content':{'episode':1,'panel':1,'description':'原稿'}}).json()
            with app.state.store.db() as db:db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(script['id'],))
            submitted=c.post(base+'/production-jobs',json={'operation':'rewrite','refs':[{'id':script['id'],'version':1}],'instruction':'修改描述','submission_id':'real-recovery'})
            assert submitted.status_code==200,submitted.text
            tid=submitted.json()['ids'][0]
            task=next(t for t in c.get(base+'/tasks').json() if t['id']==tid)
            assert task['status']=='failed',task
            with app.state.store.db() as db:
                attempt=dict(db.execute('SELECT * FROM production_attempts WHERE task_id=?',(tid,)).fetchone());aid=attempt['id']
                before=json.loads(db.execute('SELECT payload FROM tasks WHERE id=?',(tid,)).fetchone()[0])
            assert attempt['status']=='error' and len(saved)==1 and len(requests)==1
            monkeypatch.setattr(runtime,'_tool',original);c.portal.call(runtime.start)
            path=base+f'/production-jobs/{tid}/attempts/{aid}'
            details=c.get(path+'/tool-receipts');assert details.status_code==200,details.text
            assert details.json()['recovery_available'] is True,details.text
            recovered=c.post(path+'/recover-tools',json={'confirm':True});assert recovered.status_code==200,recovered.text
            assert recovered.json()['checkpoint']['model_requests']==1 and recovered.json()['checkpoint']['tool_calls']==1
            assert len(requests)==1
            assert c.post(path+'/recover-tools',json={'confirm':True}).status_code==200
            continued=c.post(path+'/continue',json={'confirm':True});assert continued.status_code==200,continued.text
            assert len(requests)==2 and any(m['role']=='tool' for m in requests[-1]['messages'])
            assert c.post(path+'/continue',json={'confirm':True}).status_code==200
            with app.state.store.db() as db:
                attempts=[dict(x) for x in db.execute('SELECT * FROM production_attempts WHERE task_id=? ORDER BY rowid',(tid,))]
                after=json.loads(db.execute('SELECT payload FROM tasks WHERE id=?',(tid,)).fetchone()[0])
                assert len(attempts)==2 and attempts[0]['attempt']==attempts[1]['attempt']==1
                assert attempts[1]['status']=='valid',attempts
                assert after['source']==before['source']=='mock'
                assert after['input_refs']==before['input_refs']
                assert db.execute('SELECT COUNT(*) FROM production_tool_calls WHERE attempt_id=?',(aid,)).fetchone()[0]==1
                assert db.execute('SELECT COUNT(*) FROM production_continuations WHERE parent_id=?',(aid,)).fetchone()[0]==1
    finally:server.shutdown();server.server_close()
