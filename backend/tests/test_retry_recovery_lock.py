from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import dump


def test_task_retry_cannot_bypass_pending_tool_recovery_lock(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        pid=client.post('/api/projects',json={'name':'synthetic pending recovery'}).json()['id']
        payload={'workflow':True,'operation':'range'}
        with client.app.state.store.db() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('task',pid,'failed',dump(payload),None,'interrupted','now','now'))
            db.execute('INSERT INTO production_attempts VALUES(?,?,?,?,?,?,?)',('attempt','task',1,'error','',None,'now'))
            db.execute('INSERT INTO pi_recovery_locks VALUES(?,?,?,?,?)',(pid,'production_attempt','attempt','repair','{}'))
        response=client.post(f'/api/projects/{pid}/tasks/task/retry')
        assert response.status_code==409,response.text
        with client.app.state.store.db() as db:
            assert db.execute("SELECT status FROM tasks WHERE id='task'").fetchone()[0]=='failed'
            assert db.execute('SELECT COUNT(*) FROM production_attempts').fetchone()[0]==1
