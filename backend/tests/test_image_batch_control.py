import time
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture
from backend.tests.test_image_batches import packages,request,wait,slow_provider


def settled(c,b,bid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        value=c.get(b+'/image-batches/'+bid).json()
        if value['status'] not in ('queued','running','pausing'):return value
        time.sleep(.01)
    raise AssertionError(value)


def test_pause_preserves_inflight_candidate_and_resume_uses_same_authorization(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'暂停与继续'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        try:
            response=c.post(b+'/image-batches/'+batch['id']+'/pause',json={});assert response.status_code==200,response.text
            assert response.json()['status']=='pausing'
            assert c.post(b+'/image-batches/'+batch['id']+'/recover',json={}).status_code==409
        finally:release.set()
        paused=settled(c,b,batch['id']);assert paused['status']=='paused' and len(calls)==1
        assert [j['status'] for j in paused['jobs']]==['succeeded','preview']
        assert paused['jobs'][0]['output']['adopted']==0 and paused['payload']['runtime']['checkpoint']['reason']=='paused'
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});done=settled(c,b,batch['id'])
        assert done['status']=='completed' and len(calls)==2
        assert done['jobs'][0]['output_id']==paused['jobs'][0]['output_id']


def test_waiting_for_user_does_not_reset_or_advance_effective_time(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);clock=[0.];app.state.image_batch_control.now=lambda:clock[0]
    entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'有效时间'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();assert batch['runtime']['hard_limit_seconds']==25200
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        clock[0]=10
        try:c.post(b+'/image-batches/'+batch['id']+'/pause',json={})
        finally:release.set()
        paused=settled(c,b,batch['id']);assert paused['runtime']['effective_seconds']==10
        clock[0]+=100000
        assert c.get(b+'/image-batches/'+batch['id']).json()['runtime']['effective_seconds']==10
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});done=settled(c,b,batch['id'])
        assert done['status']=='completed' and done['runtime']['effective_seconds']==10 and len(calls)==2


def test_hard_limit_stops_new_dispatch_keeps_return_and_recovery_cannot_reset_budget(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);clock=[0.];app.state.image_batch_control.now=lambda:clock[0];entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'七小时硬限'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        clock[0]=25201;release.set();done=settled(c,b,batch['id'])
        assert done['status']=='budget_exhausted' and len(calls)==1 and done['jobs'][0]['output_id']
        assert done['runtime']['target_reached'] is True and done['runtime']['effective_seconds']>=25200
        assert c.post(b+'/image-batches/'+batch['id']+'/recover',json={}).status_code==409
        assert len(calls)==1


def test_clock_checkpoint_loss_stops_new_dispatch_instead_of_running_without_a_clock(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'时钟失联保护'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        app.state.image_batch_control.leases.clear();release.set();done=settled(c,b,batch['id'])
        assert done['status']=='interrupted' and len(calls)==1
        assert done['runtime']['uncertain_seconds']>0


def test_rolled_back_clock_refresh_keeps_the_last_committed_observation(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);clock=[0.];app.state.image_batch_control.now=lambda:clock[0];entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'计时写入回滚'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        clock[0]=3
        try:
            try:
                with app.state.store.db() as db:
                    db.execute('BEGIN IMMEDIATE');app.state.image_batch_control.touch(db,pid,batch['id']);raise RuntimeError('synthetic rollback after refresh')
            except RuntimeError:pass
            clock[0]=7
            assert c.get(b+'/image-batches/'+batch['id']).json()['runtime']['effective_seconds']==7
        finally:release.set()
        assert settled(c,b,batch['id'])['runtime']['effective_seconds']==7


def test_pause_during_inspection_keeps_report_and_resumes_one_repair_without_reinspection(tmp_path,monkeypatch):
    import asyncio,threading
    from backend.tests.test_image_postprocess import setup,report
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report()]);original=app.state.pi_runtime.request;entered=threading.Event();release=threading.Event()
    async def delayed(command,**kw):
        if command=='complete' and not entered.is_set():
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(command,**kw)
    monkeypatch.setattr(app.state.pi_runtime,'request',delayed)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'检查暂停恢复'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        try:assert c.post(b+'/image-batches/'+batch['id']+'/pause',json={}).status_code==200
        finally:release.set()
        paused=settled(c,b,batch['id']);assert paused['status']=='paused' and len(images)==len(vision)==1
        assert paused['jobs'][0]['inspection']['report'] and not paused['jobs'][0].get('repair')
        assert paused['jobs'][0]['payload']['postprocess']['status']=='paused'
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});done=settled(c,b,batch['id'])
        assert done['status']=='completed' and len(images)==len(vision)==2
        assert done['jobs'][0]['inspection']['id']==paused['jobs'][0]['inspection']['id']


def test_unclean_restart_marks_unknown_time_upper_bound_and_cannot_reset_hard_limit(tmp_path,monkeypatch):
    import json
    from backend.app import create_app
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'异常计时恢复'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json=request(ps)).json()
        # Explicit synthetic crash checkpoint; not an actual OS power failure.
        with app.state.store.db() as db:
            p=batch['payload'];p['runtime'].update(charged_seconds=25200,reserved_seconds=10,lease_id='lost',lease_wall_started=time.time()-100)
            db.execute("UPDATE image_batches SET status='running',payload=? WHERE id=?",(json.dumps(p),batch['id']))
    restored=create_app(tmp_path)
    with TestClient(restored) as c:
        value=c.get(b+'/image-batches/'+batch['id']).json()
        assert value['status']=='budget_exhausted' and value['runtime']['uncertain_seconds']==10
        assert value['runtime']['confirmed_seconds']==25190 and not calls
        assert c.post(b+'/image-batches/'+batch['id']+'/recover',json={}).status_code==409


def test_clean_restart_preserves_pause_and_excludes_application_downtime(tmp_path,monkeypatch):
    from backend.app import create_app
    app,calls=fixture(tmp_path,monkeypatch);clock=[0.];app.state.image_batch_control.now=lambda:clock[0];entered,release=slow_provider(app);transport=app.state.image_provider.transport
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'正常关闭计时'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3);clock[0]=8
        try:c.post(b+'/image-batches/'+batch['id']+'/pause',json={})
        finally:release.set()
        assert settled(c,b,batch['id'])['runtime']['effective_seconds']==8
    restored=create_app(tmp_path);restored.state.image_provider.transport=transport;restored.state.image_batch_control.now=lambda:1000000.
    with TestClient(restored) as c:
        value=c.get(b+'/image-batches/'+batch['id']).json();assert value['status']=='paused' and value['runtime']['effective_seconds']==8 and len(calls)==1
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=settled(c,b,batch['id'])
        assert final['status']=='completed' and final['runtime']['effective_seconds']==8 and len(calls)==2


def test_hard_limit_during_vision_keeps_report_but_never_dispatches_repair(tmp_path,monkeypatch):
    import asyncio,threading
    from backend.tests.test_image_postprocess import setup,report
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical')]);clock=[0.];app.state.image_batch_control.now=lambda:clock[0];original=app.state.pi_runtime.request;entered=threading.Event();release=threading.Event()
    async def delayed(command,**kw):
        if command=='complete':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(command,**kw)
    monkeypatch.setattr(app.state.pi_runtime,'request',delayed)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'检查中硬限'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        clock[0]=25201;release.set();done=settled(c,b,batch['id'])
        assert done['status']=='budget_exhausted' and len(images)==len(vision)==1
        assert done['jobs'][0]['inspection']['report'] and not done['jobs'][0].get('repair')


def test_draining_paused_workers_still_count_toward_global_batch_capacity(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'暂停收尾仍占容量'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,9)
        batches=[c.post(b+'/image-batches',json=request([p],str(i))).json() for i,p in enumerate(ps)]
        try:
            for batch in batches[:8]:assert c.post(b+'/image-batches/'+batch['id']+'/start',json={}).status_code==200
            assert entered.wait(3)
            for batch in batches[:8]:assert c.post(b+'/image-batches/'+batch['id']+'/pause',json={}).status_code==200
            assert c.post(b+'/image-batches/'+batches[8]['id']+'/start',json={}).status_code==429
        finally:release.set()
        for batch in batches[:8]:assert settled(c,b,batch['id'])['status']=='paused'
        assert c.post(b+'/image-batches/'+batches[8]['id']+'/start',json={}).status_code==200
        assert settled(c,b,batches[8]['id'])['status']=='completed'


def test_legacy_batch_exposes_unknown_history_and_persists_new_accounting_without_replaying(tmp_path,monkeypatch):
    import json
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'旧批次增量计时'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json=request(ps)).json()
        with app.state.store.db() as db:
            p=batch['payload'];p.pop('runtime');db.execute('UPDATE image_batches SET payload=? WHERE id=?',(json.dumps(p),batch['id']))
        assert c.get(b+'/image-batches/'+batch['id']).json()['runtime']['historical_time_unknown'] is True
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=settled(c,b,batch['id'])
        assert done['status']=='completed' and done['runtime']['historical_time_unknown'] is True and len(calls)==1


def test_unclean_time_upper_bound_distinguishes_known_time_and_clock_anomalies(tmp_path,monkeypatch):
    import json
    app,calls=fixture(tmp_path,monkeypatch);app.state.image_batch_control.wall=lambda:1000.
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'未知时间上界核对'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,4)
        for index,(last,expected) in enumerate([(900.,105.),(995.,15.),(1001.,25200.),(None,25200.)]):
            batch=c.post(b+'/image-batches',json=request([ps[index]],str(index))).json()
            with app.state.store.db() as db:
                p=batch['payload'];p['runtime'].update(charged_seconds=15.,reserved_seconds=10.,lease_id='lost-'+str(index),lease_wall_started=last)
                db.execute("UPDATE image_batches SET status='running',payload=? WHERE id=?",(json.dumps(p),batch['id']))
            app.state.image_batch_control.reconcile()
            result=c.get(b+'/image-batches/'+batch['id']).json()
            assert result['runtime']['effective_seconds']==expected
            assert result['runtime']['confirmed_seconds']==5
            assert result['runtime']['uncertain_seconds']==expected-5
            assert result['status']==('budget_exhausted' if expected==25200 else 'interrupted')
        assert not calls
