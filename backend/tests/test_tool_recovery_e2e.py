"""Actual lost host acknowledgement, actual SDK file repair, explicit new allowance."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from fastapi.testclient import TestClient
from backend.app import create_app
import backend.app as app_module


def test_actual_host_saved_then_node_killed_recovery_never_replays_tool(tmp_path,monkeypatch):
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            if len(requests)==1:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'saved-read','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]};reason='tool_calls'
            else:delta={'role':'assistant','content':'已依据原工具结果继续，未重复查询。'};reason='stop'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for change,finish in ((delta,None),({},reason)):
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':change,'finish_reason':finish}]}
                if finish:chunk['usage']={'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setattr(app_module.vault,'get_password',lambda *a:'synthetic-recovery-key')
    try:
        with TestClient(create_app(tmp_path)) as client:
            app=client.app;runtime=app.state.pi_runtime
            original_tool=runtime._tool
            saved=[]
            async def drop_ack(message,on_tool):
                saved.append(await on_tool(message))
                runtime.process.kill()
            monkeypatch.setattr(runtime,'_tool',drop_ack)
            pid=client.post('/api/projects',json={'name':'synthetic crash recovery'}).json()['id'];base=f'/api/projects/{pid}'
            with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            sid=client.post(base+'/agent/sessions',json={'stage':'memory'}).json()['id']
            sent=client.post(base+f'/agent/sessions/{sid}/messages',json={'message':'读取后继续','expected_version':0})
            assert sent.status_code==200,sent.text
            rid=sent.json()['id'];path=base+f'/agent/runs/{rid}'
            def wait_terminal(url):
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    value=client.get(url).json()
                    if value['status'] not in ('queued','running','recovering'):return value
                    time.sleep(.03)
                raise AssertionError(value)
            interrupted=wait_terminal(path)
            assert interrupted['status']=='interrupted',interrupted
            assert len(saved)==1 and len(requests)==1
            monkeypatch.setattr(runtime,'_tool',original_tool)
            client.portal.call(runtime.start)
            details=client.get(path+'/tool-receipts')
            assert details.status_code==200,details.text
            assert details.json()['recovery_available'] is True,details.text
            assert details.json()['receipts'][0]['state']=='host_saved_node_unconfirmed'
            body={'confirm':True,'expected_version':1}
            repaired=client.post(path+'/recover-tools',json=body)
            assert repaired.status_code==200,repaired.text
            value=repaired.json();assert value['status']=='paused',value
            assert value['checkpoint']['model_requests']==1 and value['checkpoint']['tool_calls']==1
            assert value['checkpoint']['unresolved_tools']==0
            assert len(requests)==1
            assert client.post(path+'/recover-tools',json=body).status_code==200
            assert len(requests)==1
            resumed=client.post(path+'/continue',json=body)
            assert resumed.status_code==200,resumed.text
            child=wait_terminal(base+'/agent/runs/'+resumed.json()['id'])
            assert child['status']=='completed',child
            assert child['reply']=='已依据原工具结果继续，未重复查询。'
            assert len(requests)==2
            assert any(m['role']=='tool' for m in requests[-1]['messages'])
            with app.state.store.db() as db:
                assert db.execute('SELECT COUNT(*) FROM agent_tool_calls WHERE run_id=?',(rid,)).fetchone()[0]==1
                assert db.execute('SELECT COUNT(*) FROM pi_tool_receipts WHERE owner_id=?',(rid,)).fetchone()[0]==1
            assert 'synthetic-recovery-key' not in json.dumps(value)
    finally:server.shutdown();server.server_close()
