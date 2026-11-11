import asyncio
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.capacity import CapacityManager,CapacityCancelled
from backend.agent_runtime import PiRuntime,RuntimeUnavailable


def test_text_capacity_is_fifo_shared_and_resizing_never_cancels_active_work():
    async def check():
        manager=CapacityManager();pool=manager.pools['text'];entered=[];release=asyncio.Event()
        async def work(i):
            async with pool.hold(str(i)):
                entered.append(i);await release.wait()
        tasks=[asyncio.create_task(work(i)) for i in range(5)]
        await asyncio.sleep(.02);assert entered==[0,1] and pool.snapshot()=={'limit':2,'active':2,'waiting':3}
        await pool.resize(1);assert pool.snapshot()['active']==2
        await pool.resize(3);await asyncio.sleep(.02);assert entered==[0,1,2]
        pool.cancel('3');await asyncio.sleep(.02);assert pool.snapshot()['waiting']==1
        release.set();results=await asyncio.gather(*tasks,return_exceptions=True)
        assert isinstance(results[3],CapacityCancelled) and entered==[0,1,2,4]
        assert pool.snapshot()=={'limit':3,'active':0,'waiting':0}
    asyncio.run(check())


def test_capacity_settings_are_versioned_persistent_and_contain_no_credentials(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        initial=c.get('/api/runtime/limits');assert initial.status_code==200,initial.text
        assert initial.json()['limits']=={'text':2,'image':1,'vision':1}
        body={'expected_revision':initial.json()['revision'],'limits':{'text':1,'image':2,'vision':2}}
        changed=c.put('/api/runtime/limits',json=body);assert changed.status_code==200,changed.text
        assert c.put('/api/runtime/limits',json=body).status_code==409
        for value in (0,9,True):
            assert c.put('/api/runtime/limits',json={**body,'limits':{**body['limits'],'text':value}}).status_code==422
        assert 'secret' not in changed.text
    with TestClient(create_app(tmp_path)) as c:assert c.get('/api/runtime/limits').json()['limits']==body['limits']


def test_global_transport_counts_all_text_commands_and_control_bypasses_full_capacity(tmp_path,monkeypatch):
    async def check():
        manager=CapacityManager();runtime=PiRuntime(tmp_path,capacity=manager);runtime.status='ready';runtime.process=SimpleNamespace(returncode=None);sent=[]
        async def send(m):
            sent.append(m)
            if m['type'] in ('health','cancel'):runtime.pending[m['request_id']][0].set_result({'v':1,'type':'result','data':{'protocol':1}})
        monkeypatch.setattr(runtime,'_send',send)
        tasks=[asyncio.create_task(runtime.request(kind,run_id=str(i),timeout=3)) for i,kind in enumerate(['run','setup','complete'])]
        await asyncio.sleep(.03);assert [m['run_id'] for m in sent]==['0','1']
        assert (await runtime.request('health',timeout=.2))['data']['protocol']==1
        await runtime.request('cancel',run_id='2',timeout=.2)
        await asyncio.sleep(.03);assert not any(m.get('run_id')=='2' and m['type']=='complete' for m in sent)
        for m in list(sent):
            entry=runtime.pending.get(m['request_id'])
            if entry and not entry[0].done():entry[0].set_result({'v':1,'type':'result','data':{}})
        result=await asyncio.gather(*tasks,return_exceptions=True)
        assert isinstance(result[2],RuntimeUnavailable)
        assert manager.pools['text'].snapshot()['active']==0 and not runtime.pending
    asyncio.run(check())


def test_dispatch_guard_runs_after_capacity_wait_and_prevents_a_stale_request(tmp_path,monkeypatch):
    async def check():
        manager=CapacityManager();await manager.pools['text'].resize(1);runtime=PiRuntime(tmp_path,capacity=manager);runtime.status='ready';runtime.process=SimpleNamespace(returncode=None);sent=[];allowed=[True]
        async def send(m):sent.append(m);runtime.pending[m['request_id']][0].set_result({'v':1,'type':'result','data':{}})
        monkeypatch.setattr(runtime,'_send',send)
        def guard():
            if not allowed[0]:raise RuntimeError('stale synthetic input')
        async with manager.pools['text'].hold('holder'):
            task=asyncio.create_task(runtime.request('run',run_id='waiting',before_dispatch=guard));await asyncio.sleep(.02);allowed[0]=False
            assert not sent
        with pytest.raises(RuntimeError,match='stale'):await task
        assert not sent and manager.pools['text'].snapshot()['active']==0
    asyncio.run(check())


def test_async_dispatch_guard_refreshes_secret_only_after_wait(tmp_path,monkeypatch):
    async def check():
        runtime=PiRuntime(tmp_path);runtime.status='ready';runtime.process=SimpleNamespace(returncode=None);sent=[]
        async def send(message):
            sent.append(message);runtime.pending[message['request_id']][0].set_result({'v':1,'type':'result','data':{}})
        monkeypatch.setattr(runtime,'_send',send)
        async def guard():return {'secret':'synthetic-refreshed'}
        await runtime.request('complete',run_id='refresh',secret='synthetic-old',before_dispatch=guard)
        assert sent[0]['secret']=='synthetic-refreshed'
        assert runtime.capacity.pools['text'].snapshot()['active']==0
    asyncio.run(check())


@pytest.mark.parametrize('change',['cancel','config','missing_key','rotate','unchanged'])
def test_queued_setup_revalidates_before_model_submission(tmp_path,monkeypatch,change):
    import json
    import time
    from backend.tests.test_setup_assistant import fixture,wait
    app,vault,_=fixture(tmp_path,monkeypatch,real_runtime=True);runtime=app.state.pi_runtime;calls=[]
    original=runtime._exchange
    async def exchange(command,*args,**kwargs):
        if command!='setup':return await original(command,*args,**kwargs)
        calls.append(kwargs)
        return {'type':'result','data':{'text':json.dumps({'reply':'合成建议','actions':[]})}}
    monkeypatch.setattr(runtime,'_exchange',exchange)
    with TestClient(app) as c:
        c.put('/api/runtime/limits',json={'expected_revision':0,'limits':{'text':1,'image':1,'vision':1}})
        c.portal.call(app.state.capacity.pools['text'].acquire)
        try:
            sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
            sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'检查配置','expected_version':0})
            assert sent.status_code==200,sent.text
            rid=sent.json()['id']
            for _ in range(100):
                if c.get('/api/runtime/limits').json()['usage']['text']['waiting']==1:break
                time.sleep(.01)
            else:pytest.fail('setup did not enter shared text queue')
            assert not calls
            assert c.get('/api/agent/health').status_code==200
            if change=='cancel':assert c.post(f'/api/setup-assistant/runs/{rid}/cancel').status_code==200
            elif change=='config':
                with app.state.store.db() as db:db.execute('UPDATE settings SET content=? WHERE id=1',(json.dumps({'text':{'url':'http://127.0.0.1:1/v1','model':'changed'}}),))
            elif change=='missing_key':vault.values.pop('text')
            elif change=='rotate':vault.values['text']='synthetic-rotated-key'
        finally:c.portal.call(app.state.capacity.pools['text'].release)
        result=wait(c,sid,rid)
        if change in ('rotate','unchanged'):
            assert result['status']=='completed',result
            assert len(calls)==1
            assert calls[0]['secret']==vault.values['text']
        else:
            assert result['status'] in ('cancelled','interrupted'),result
            assert not calls
        assert 'synthetic-rotated-key' not in (tmp_path/'workbench.sqlite').read_bytes().decode('latin1')


@pytest.mark.parametrize('change',['record','cancel','config'])
def test_queued_project_discussion_rechecks_attached_version_and_state(tmp_path,monkeypatch,change):
    import time
    from backend.tests.test_setup_assistant import fixture
    app,_,_=fixture(tmp_path,monkeypatch,real_runtime=True);runtime=app.state.pi_runtime;calls=[];original=runtime._exchange
    async def exchange(command,*args,**kwargs):
        if command!='run':return await original(command,*args,**kwargs)
        calls.append(kwargs);return {'type':'result','data':{'text':'synthetic reply'}}
    monkeypatch.setattr(runtime,'_exchange',exchange)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'排队讨论'}).json()['id'];base=f'/api/projects/{pid}'
        record=c.post(base+'/records',json={'kind':'outline','title':'细纲','content':{'text':'原稿'}}).json()
        sid=c.post(base+'/agent/sessions',json={'stage':'outline','refs':[{'id':record['id'],'version':1}]}).json()['id']
        c.put('/api/runtime/limits',json={'expected_revision':0,'limits':{'text':1,'image':1,'vision':1}})
        c.portal.call(app.state.capacity.pools['text'].acquire)
        try:
            rid=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'讨论这份细纲','expected_version':0}).json()['id']
            for _ in range(100):
                if c.get('/api/runtime/limits').json()['usage']['text']['waiting']==1:break
                time.sleep(.01)
            else:pytest.fail('discussion did not queue')
            if change=='record':
                with app.state.store.db() as db:app.state.store.save(db,pid,record['id'],1,{'text':'人工新稿'})
            elif change=='cancel':assert c.post(base+f'/agent/runs/{rid}/cancel').status_code==200
            else:
                with app.state.store.db() as db:db.execute("UPDATE settings SET content='{}' WHERE id=1")
        finally:c.portal.call(app.state.capacity.pools['text'].release)
        for _ in range(100):
            result=c.get(base+f'/agent/runs/{rid}').json()
            if result['status'] not in ('queued','running'):break
            time.sleep(.01)
        assert result['status'] in ('interrupted','cancelled'),result
        assert not calls


@pytest.mark.parametrize('change',['record','cancel'])
def test_queued_production_rechecks_input_and_authorization(tmp_path,monkeypatch,change):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from backend.tests.test_setup_assistant import fixture
    app,_,_=fixture(tmp_path,monkeypatch,real_runtime=True);runtime=app.state.pi_runtime;calls=[];original=runtime._exchange
    async def exchange(command,*args,**kwargs):
        if command!='run':return await original(command,*args,**kwargs)
        calls.append(kwargs);raise AssertionError('stale production must not reach provider')
    monkeypatch.setattr(runtime,'_exchange',exchange)
    with TestClient(app) as c,ThreadPoolExecutor(max_workers=1) as executor:
        pid=c.post('/api/projects',json={'name':'排队生产'}).json()['id'];base=f'/api/projects/{pid}'
        record=c.post(base+'/records',json={'kind':'script','title':'脚本','content':{'episode':1,'panel':1,'description':'原稿'}}).json()
        c.put('/api/runtime/limits',json={'expected_revision':0,'limits':{'text':1,'image':1,'vision':1}})
        c.portal.call(app.state.capacity.pools['text'].acquire)
        try:
            future=executor.submit(c.post,base+'/production-jobs',json={'operation':'rewrite','refs':[{'id':record['id'],'version':1}],'instruction':'修改天气','submission_id':'queued'})
            for _ in range(100):
                if c.get('/api/runtime/limits').json()['usage']['text']['waiting']==1:break
                time.sleep(.01)
            else:pytest.fail('production did not queue')
            if change=='record':
                with app.state.store.db() as db:app.state.store.save(db,pid,record['id'],1,{'episode':1,'panel':1,'description':'人工新稿'})
            else:
                tid=c.get(base+'/tasks').json()[0]['id']
                assert c.post(base+f'/production-jobs/{tid}/cancel').status_code==200
        finally:c.portal.call(app.state.capacity.pools['text'].release)
        assert future.result(timeout=5).status_code==200
        task=c.get(base+'/tasks').json()[0]
        assert task['status'] in ('cancelled','failed'),task
        assert task['output_id'] is None and not calls


@pytest.mark.parametrize('change',['cancel','config','parse'])
def test_queued_graph_unit_rechecks_job_configuration_and_parse(tmp_path,monkeypatch,change):
    import time
    from backend.tests.test_setup_assistant import fixture
    app,_,_=fixture(tmp_path,monkeypatch,real_runtime=True);runtime=app.state.pi_runtime;calls=[];original=runtime._exchange
    async def exchange(command,*args,**kwargs):
        if command!='complete':return await original(command,*args,**kwargs)
        calls.append(kwargs);raise AssertionError('invalidated graph must not reach provider')
    monkeypatch.setattr(runtime,'_exchange',exchange)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'排队图谱'}).json()['id'];base=f'/api/projects/{pid}'
        c.put('/api/runtime/limits',json={'expected_revision':0,'limits':{'text':1,'image':1,'vision':1}})
        c.portal.call(app.state.capacity.pools['text'].acquire)
        try:
            document=c.post(base+'/documents',files={'file':('测试.txt','第一章\n人物归乡。'.encode(),'text/plain')}).json()
            for _ in range(150):
                if c.get('/api/runtime/limits').json()['usage']['text']['waiting']>=1:break
                time.sleep(.01)
            else:pytest.fail('graph did not queue')
            jid=c.get(base+'/graph/jobs').json()[0]['id']
            if change=='cancel':assert c.post(base+f'/graph/jobs/{jid}/cancel').status_code==200
            elif change=='config':
                with app.state.store.db() as db:db.execute("UPDATE settings SET content='{}' WHERE id=1")
            else:
                # Only alter this synthetic parse head, leaving the queued job intact to exercise its guard.
                with app.state.store.db() as db:db.execute('UPDATE documents SET parse_version=parse_version+1 WHERE id=?',(document['id'],))
        finally:c.portal.call(app.state.capacity.pools['text'].release)
        for _ in range(150):
            usage=c.get('/api/runtime/limits').json()['usage']['text']
            if not usage['active'] and not usage['waiting']:break
            time.sleep(.01)
        assert usage['active']==0 and usage['waiting']==0
        assert not calls
