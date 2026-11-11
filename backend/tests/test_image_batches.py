import time
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture


def packages(c,b,count=2):
    return [c.post(b+'/records',json={'kind':'package','title':f'第1话第{i+1}格','content':{'episode':1,'panel':i+1,'prompt':f'第{i+1}格完整提示词','references':[]}}).json() for i in range(count)]


def request(values,token='batch'):
    return {'submission_id':token,'packages':[{'id':r['id'],'version':r['version']} for r in values]}


def wait(c,b,bid):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        value=c.get(b+'/image-batches/'+bid).json()
        if value['status'] not in ('queued','running'):return value
        time.sleep(.01)
    raise AssertionError(value)


def test_batch_preview_never_calls_and_explicit_start_produces_unadopted_candidates(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'真实独立批次'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        with app.state.store.db() as db:db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(pkgs[0]['id'],))
        response=c.post(b+'/image-batches',json=request(pkgs));assert response.status_code==200,response.text
        preview=response.json();assert preview['status']=='preview' and not calls and len(preview['jobs'])==2
        assert c.post(b+'/image-batches',json=request(pkgs)).json()['id']==preview['id']
        assert c.post(b+'/image-batches/'+preview['id']+'/start',json={}).status_code==200
        done=wait(c,b,preview['id']);assert done['status']=='completed',done
        assert len(calls)==2 and all(j['output']['adopted']==0 for j in done['jobs'])
        assert [j['output']['content']['panel'] for j in done['jobs']]==[1,2]
        assert [j['output']['source'] for j in done['jobs']]==['mock','ai']
        assert c.post(b+'/image-batches/'+preview['id']+'/start',json={}).status_code==200 and len(calls)==2


def test_batch_start_checks_all_frozen_inputs_before_any_submission(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'全批冻结'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        result=c.post(b+'/image-batches',json=request(pkgs));assert result.status_code==200,result.text
        bid=result.json()['id'];last=pkgs[-1]
        c.put(b+'/records/'+last['id'],json={'expected_version':1,'content':{**last['content'],'prompt':'新版本'}})
        assert c.post(b+'/image-batches/'+bid+'/start',json={}).status_code==409 and not calls


def test_duplicate_slots_and_unimplemented_real_dependencies_are_rejected_without_calls(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'批次依赖'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        assert c.post(b+'/image-batches',json=request([pkgs[0],pkgs[0]])).status_code==422
        r=pkgs[1];c.put(b+'/records/'+r['id'],json={'expected_version':1,'content':{**r['content'],'generation_dependencies':[{'episode':1,'panel':1}]}})
        r=c.get(b+'/records/'+r['id']).json()
        assert c.post(b+'/image-batches',json=request([pkgs[0],r])).status_code==422
        assert not calls and c.get(b+'/image-jobs?kind=image').json()==[]


def test_malformed_package_prompt_fails_with_validation_error_before_preview(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'无效包'}).json()['id'];b=f'/api/projects/{pid}';p=packages(c,b,1)[0]
        c.put(b+'/records/'+p['id'],json={'expected_version':1,'content':{**p['content'],'prompt':None}})
        p=c.get(b+'/records/'+p['id']).json()
        assert c.post(b+'/image-batches',json=request([p])).status_code==422
        assert not calls


def test_cancel_during_preview_is_not_overwritten_by_late_preparation(tmp_path,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_jobs.preview;entered=threading.Event();release=threading.Event()
    def paused(*args):
        entered.set();release.wait(4);return original(*args)
    monkeypatch.setattr(app.state.image_jobs,'preview',paused)
    with TestClient(app) as c,ThreadPoolExecutor(max_workers=1) as pool:
        pid=c.post('/api/projects',json={'name':'预览停止'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        pending=pool.submit(c.post,b+'/image-batches',json=request(pkgs))
        assert entered.wait(2)
        try:
            bid=c.get(b+'/image-batches').json()['items'][0]['id']
            assert c.post(b+'/image-batches/'+bid+'/cancel',json={}).json()['status']=='cancelled'
        finally:release.set()
        response=pending.result(timeout=5);assert response.status_code==200,response.text
        result=c.get(b+'/image-batches/'+bid).json()
        assert result['status']=='cancelled' and not calls
        assert all(j['status']=='cancelled' for j in result['jobs'])
        assert len(c.get(b+'/image-jobs?kind=image').json())==len(result['jobs'])


def slow_provider(app):
    import asyncio,threading,httpx
    entered=threading.Event();release=threading.Event();original=app.state.image_provider.transport
    async def handler(req):
        entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return await original.handle_async_request(req)
    app.state.image_provider.transport=httpx.MockTransport(handler)
    return entered,release


def test_cancel_inflight_preserves_original_return_and_never_starts_remaining_panels(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'在途停止'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(pkgs)).json();bid=batch['id']
        c.post(b+'/image-batches/'+bid+'/start',json={});assert entered.wait(2)
        try:assert c.post(b+'/image-batches/'+bid+'/cancel',json={}).json()['status']=='cancelled'
        finally:release.set()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=c.get(b+'/image-batches/'+bid).json()
            if result['jobs'][0]['call']['status']=='completed':break
            time.sleep(.01)
        assert len(calls)==1 and result['jobs'][0]['call']['status']=='completed'
        assert all(j['status']=='cancelled' and not j['output_id'] for j in result['jobs'])
        assert c.post(b+'/image-batches/'+bid+'/recover',json={}).status_code==409


def test_changed_later_package_is_blocked_after_first_return_without_submitting_it(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);entered,release=slow_provider(app)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'等待中改包'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        bid=c.post(b+'/image-batches',json=request(pkgs)).json()['id']
        c.post(b+'/image-batches/'+bid+'/start',json={});assert entered.wait(2)
        try:c.put(b+'/records/'+pkgs[1]['id'],json={'expected_version':1,'content':{**pkgs[1]['content'],'prompt':'等待中修改'}})
        finally:release.set()
        done=wait(c,b,bid)
        assert done['status']=='needs_attention' and len(calls)==1
        assert [j['status'] for j in done['jobs']]==['succeeded','blocked']


def test_unknown_panel_is_not_reposted_and_independent_remaining_panel_continues(tmp_path,monkeypatch):
    import httpx
    app,_=fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;calls=[]
    async def handler(req):
        calls.append(req)
        if len(calls)==1:return httpx.Response(500,json={'error':'uncertain'})
        return await original.handle_async_request(req)
    app.state.image_provider.transport=httpx.MockTransport(handler)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'批次未知'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        bid=c.post(b+'/image-batches',json=request(pkgs)).json()['id'];c.post(b+'/image-batches/'+bid+'/start',json={})
        done=wait(c,b,bid)
        assert done['status']=='needs_attention' and len(calls)==2
        assert [j['status'] for j in done['jobs']]==['unknown','succeeded']
        c.post(b+'/image-batches/'+bid+'/recover',json={});again=wait(c,b,bid)
        assert again['status']=='needs_attention' and len(calls)==2


def test_restart_never_dispatches_and_explicit_recovery_skips_already_saved_candidate(tmp_path,monkeypatch):
    from backend.app import create_app
    app,calls=fixture(tmp_path,monkeypatch);transport=app.state.image_provider.transport
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'批次重启'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(pkgs)).json();bid=batch['id']
        from fastapi import BackgroundTasks
        # Synthetic authorized checkpoint uses the same clock admission as the host.
        with app.state.store.db() as db:
            db.execute("UPDATE image_batches SET status='running' WHERE id=?",(bid,));app.state.image_batch_control.touch(db,pid,bid)
        background=BackgroundTasks();app.state.image_jobs.queue(pid,batch['jobs'][0]['id'],background,batch_id=bid)
        c.portal.call(background);assert len(calls)==1
        with app.state.store.db() as db:db.execute("UPDATE image_batches SET status='running' WHERE id=?",(bid,))
    restored=create_app(tmp_path);restored.state.image_provider.transport=transport
    with TestClient(restored) as c:
        assert c.get(b+'/image-batches/'+bid).json()['status']=='interrupted' and len(calls)==1
        c.post(b+'/image-batches/'+bid+'/recover',json={});done=wait(c,b,bid)
        assert done['status']=='completed' and len(calls)==2
        assert done['jobs'][0]['output_id']==c.get(b+'/image-jobs/'+batch['jobs'][0]['id']).json()['output_id']


def test_cancel_tolerates_a_job_finishing_between_status_read_and_cancel(tmp_path,monkeypatch):
    from fastapi import HTTPException
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_jobs.cancel;visited=[]
    def racing(pid,jid):
        visited.append(jid)
        if len(visited)==1:
            with app.state.store.db() as db:db.execute("UPDATE image_jobs SET status='succeeded' WHERE id=?",(jid,))
            raise HTTPException(409,'fixture: job finished during cancellation')
        return original(pid,jid)
    monkeypatch.setattr(app.state.image_jobs,'cancel',racing)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'停止竞争'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        bid=c.post(b+'/image-batches',json=request(pkgs)).json()['id']
        response=c.post(b+'/image-batches/'+bid+'/cancel',json={})
        assert response.status_code==200,response.text
        assert response.json()['status']=='cancelled' and len(visited)==2 and not calls
        assert response.json()['jobs'][1]['status']=='cancelled'


def test_batch_preview_items_cannot_bypass_batch_authorization_via_single_job_start(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'批次授权归属'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        batch=c.post(b+'/image-batches',json=request(pkgs)).json()
        assert c.post(b+'/image-jobs/'+batch['jobs'][0]['id']+'/start',json={}).status_code==409
        assert not calls and c.get(b+'/image-batches/'+batch['id']).json()['status']=='preview'


def test_shutdown_stops_dispatch_before_waiting_for_the_text_runtime_to_close(tmp_path,monkeypatch):
    import asyncio,threading,httpx
    app,_=fixture(tmp_path,monkeypatch);original_transport=app.state.image_provider.transport
    entered=threading.Event();release=threading.Event();starts=[]
    async def provider(req):
        starts.append(req);entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return await original_transport.handle_async_request(req)
    app.state.image_provider.transport=httpx.MockTransport(provider)
    index=next(i for i,handler in enumerate(app.router.on_shutdown) if getattr(handler,'__self__',None) is app.state.pi_runtime)
    original_close=app.router.on_shutdown[index]
    async def slow_close():
        release.set();await asyncio.sleep(.1);await original_close()
    app.router.on_shutdown[index]=slow_close
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'关闭先停派发'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        bid=c.post(b+'/image-batches',json=request(pkgs)).json()['id']
        c.post(b+'/image-batches/'+bid+'/start',json={});assert entered.wait(2)
    assert len(starts)==1
    with app.state.store.db() as db:assert db.execute('SELECT status FROM image_batches WHERE id=?',(bid,)).fetchone()['status']=='interrupted'


def test_malformed_falsy_dependency_is_rejected_before_creating_any_batch_jobs(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'批次依赖格式'}).json()['id'];b=f'/api/projects/{pid}';pkgs=packages(c,b)
        r=pkgs[1]
        pkgs[1]=c.put(b+'/records/'+r['id'],json={'expected_version':1,'content':{**r['content'],'generation_dependencies':{}}}).json()
        response=c.post(b+'/image-batches',json=request(pkgs))
        assert response.status_code==422,response.text
        assert not calls and c.get(b+'/image-jobs?kind=image').json()==[]
        assert c.get(b+'/image-batches').json()['total']==0
