import asyncio,json,base64
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture
from backend.tests.test_image_batches import packages,request,wait


def setup(tmp_path,monkeypatch,reports):
    app,images=fixture(tmp_path,monkeypatch);vision=[]
    with app.state.store.db() as db:
        settings=json.loads(db.execute('SELECT content FROM settings').fetchone()[0]);settings['vision']={'url':'http://fixture/v1','model':'vision-fixture','api':'openai-completions'};db.execute('UPDATE settings SET content=?',(json.dumps(settings),))
    async def runtime(command,**kw):
        if command!='complete':return {'type':'result','data':{}}
        vision.append(kw)
        value=reports[min(len(vision)-1,len(reports)-1)]
        if isinstance(value,Exception):raise value
        return {'type':'result','data':{'text':json.dumps(value,ensure_ascii=False),'usage':{'totalTokens':12}}}
    monkeypatch.setattr(app.state.pi_runtime,'request',runtime)
    return app,images,vision


def report(severity=None,category='story'):
    return {'summary':'合成实图检查','issues':[] if severity is None else [{'severity':severity,'category':category,'description':'动作与固定脚本不符','evidence':'图1人物右手未按固定提示词递信','images':[1],'region':[.2,.1,.2,.3]}]}


def test_authorized_generate_review_one_story_repair_and_recheck_keeps_both_candidates(tmp_path,monkeypatch):
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report()])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'检查有限返修'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        response=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'});assert response.status_code==200,response.text
        batch=response.json();assert not images and not vision
        assert batch['payload']['call_limits']=={'images':2,'vision':2,'image_network_attempts':2}
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert done['status']=='completed' and len(images)==2 and len(vision)==2,done
        root=done['jobs'][0];post=root['payload']['postprocess'];assert post['status']=='completed' and post['repair_job_id']!=root['id']
        repair=c.get(b+'/image-jobs/'+post['repair_job_id']).json()
        assert root['output_id']!=repair['output_id'] and post['final_job_id']==repair['id']
        assert root['output']['adopted']==repair['output']['adopted']==0
        assert root['output']['review']==repair['output']['review']=='pending'
        assert repair['payload']['repair_of']==root['id'] and repair['call']['manifest']['references'][0]['id']==root['output_id']
        assert '动作与固定脚本不符' in repair['payload']['prompt'] and '硬蒙版' in repair['payload']['prompt']
        assert base64.b64decode(vision[0]['images'][0]['data'])==base64.b64decode(vision[1]['images'][0]['data'])
        assert images[-1].url.path.endswith('/images/edits')
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});assert len(images)==2 and len(vision)==2


@pytest.mark.parametrize('severity,category',[('minor','story'),('major','story'),('critical','identity')])
def test_only_critical_story_can_trigger_automatic_repair(tmp_path,monkeypatch,severity,category):
    app,images,vision=setup(tmp_path,monkeypatch,[report(severity,category)])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'普通瑕疵交人工'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json()
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert done['status']=='completed' and len(images)==1 and len(vision)==1
        assert not done['jobs'][0]['payload']['postprocess'].get('repair_job_id')


def test_unknown_inspection_never_reposts_and_independent_generation_continues(tmp_path,monkeypatch):
    app,images,vision=setup(tmp_path,monkeypatch,[TimeoutError(),report()])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'未知检查'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        response=c.post(b+'/image-batches',json={**request(ps),'inspection':'review'});assert response.status_code==200,response.text
        batch=response.json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert done['status']=='needs_attention' and len(images)==2 and len(vision)==2
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});again=wait(c,b,batch['id'])
        assert again['status']=='needs_attention' and len(images)==2 and len(vision)==2


def test_changed_vision_configuration_blocks_entire_batch_before_generation(tmp_path,monkeypatch):
    app,images,vision=setup(tmp_path,monkeypatch,[report()])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'检查配置冻结'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review'}).json()
        with app.state.store.db() as db:
            settings=json.loads(db.execute('SELECT content FROM settings').fetchone()[0]);settings['vision']['model']='changed';db.execute('UPDATE settings SET content=?',(json.dumps(settings),))
        response=c.post(b+'/image-batches/'+batch['id']+'/start',json={})
        assert response.status_code==409 and not images and not vision


def test_reinspection_still_critical_never_creates_a_second_repair(tmp_path,monkeypatch):
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report('critical')])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'返修硬上限'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert done['status']=='completed' and done['jobs'][0]['payload']['postprocess']['needs_manual'] is True
        assert len(images)==len(vision)==2
        assert c.post(b+'/vision-reviews/'+done['jobs'][0]['inspection']['id']+'/start',json={}).status_code==409
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});assert len(images)==len(vision)==2


def test_vision_wait_does_not_hold_image_capacity_or_block_other_ready_generation(tmp_path,monkeypatch):
    import threading,time
    app,images,vision=setup(tmp_path,monkeypatch,[report()]);original=app.state.pi_runtime.request;entered=threading.Event();release=threading.Event()
    async def delayed(command,**kw):
        if command=='complete':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(command,**kw)
    monkeypatch.setattr(app.state.pi_runtime,'request',delayed)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'独立容量'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        try:
            deadline=time.monotonic()+3
            while len(images)<2 and time.monotonic()<deadline:time.sleep(.01)
            assert len(images)==2 and not app.state.image_provider.slot.locked()
        finally:release.set()
        assert wait(c,b,batch['id'])['status']=='completed'


def test_cancel_during_vision_saves_its_return_but_never_repairs(tmp_path,monkeypatch):
    import threading
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical')]);original=app.state.pi_runtime.request;entered=threading.Event();release=threading.Event()
    async def delayed(command,**kw):
        if command=='complete':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(command,**kw)
    monkeypatch.setattr(app.state.pi_runtime,'request',delayed)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'检查在途停止'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        try:assert c.post(b+'/image-batches/'+batch['id']+'/cancel',json={}).json()['status']=='cancelled'
        finally:release.set()
        import time
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            done=c.get(b+'/image-batches/'+batch['id']).json()
            if done['jobs'][0].get('inspection',{}).get('raw'):break
            time.sleep(.01)
        assert len(images)==len(vision)==1 and done['jobs'][0]['inspection']['raw']
        assert done['jobs'][0]['payload']['postprocess']['status']=='cancelled'


def test_vision_plan_is_rechecked_after_waiting_for_generation_capacity(tmp_path,monkeypatch):
    import time
    app,images,vision=setup(tmp_path,monkeypatch,[report()])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'排队检查计划'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review'}).json();c.portal.call(app.state.image_provider.slot.acquire)
        c.post(b+'/image-batches/'+batch['id']+'/start',json={})
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if c.get(b+'/image-batches/'+batch['id']).json()['jobs'][0]['status']=='running':break
                time.sleep(.01)
            else:raise AssertionError('root did not reach capacity wait')
            with app.state.store.db() as db:
                settings=json.loads(db.execute('SELECT content FROM settings').fetchone()[0]);settings['vision']['model']='changed';db.execute('UPDATE settings SET content=?',(json.dumps(settings),))
        finally:c.portal.call(app.state.image_provider.slot.release)
        done=wait(c,b,batch['id']);assert done['jobs'][0]['status']=='blocked' and not images and not vision


def test_cancel_inflight_repair_preserves_paid_return_without_registering_candidate(tmp_path,monkeypatch):
    import threading,httpx,time
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report()]);transport=app.state.image_provider.transport;entered=threading.Event();release=threading.Event()
    async def delayed(req):
        if req.url.path.endswith('/edits'):
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await transport.handle_async_request(req)
    app.state.image_provider.transport=httpx.MockTransport(delayed)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'返修在途停止'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert entered.wait(3)
        try:c.post(b+'/image-batches/'+batch['id']+'/cancel',json={})
        finally:release.set()
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            done=c.get(b+'/image-batches/'+batch['id']).json()
            if done['jobs'][0]['repair']['call']['status']=='completed':break
            time.sleep(.01)
        repair=done['jobs'][0]['repair']
        assert len(images)==2 and len(vision)==1 and repair['status']=='cancelled' and not repair['output_id']
        assert repair['call']['result']['url']


def test_dependency_uses_the_one_repair_candidate_after_review_not_the_superseded_original(tmp_path,monkeypatch):
    from backend.tests.test_image_dependencies import link,adopt_review
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report(),report()])
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'返修依赖'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});first=wait(c,b,batch['id'])
        assert first['jobs'][1]['status']=='waiting_dependency' and len(images)==2
        repaired=first['jobs'][0]['repair'];chosen=adopt_review(c,b,repaired)
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and len(images)==3 and len(vision)==3
        assert final['jobs'][1]['call']['manifest']['references'][-1]['id']==chosen['id']
        assert final['jobs'][0]['output']['adopted']==0


def test_changed_inspection_plan_while_repair_waits_prevents_the_extra_paid_image(tmp_path,monkeypatch):
    import threading,time
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical')]);original=app.state.pi_runtime.request;held=threading.Event()
    async def runtime(command,**kw):
        result=await original(command,**kw)
        if command=='complete' and not held.is_set():await app.state.image_provider.slot.acquire();held.set()
        return result
    monkeypatch.setattr(app.state.pi_runtime,'request',runtime)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'返修排队计划冻结'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});assert held.wait(3)
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                state=c.get(b+'/image-batches/'+batch['id']).json()['jobs'][0]
                if state.get('repair',{}).get('status')=='running':break
                time.sleep(.01)
            else:raise AssertionError('repair did not reach capacity wait')
            with app.state.store.db() as db:
                settings=json.loads(db.execute('SELECT content FROM settings').fetchone()[0]);settings['vision']['model']='changed';db.execute('UPDATE settings SET content=?',(json.dumps(settings),))
        finally:c.portal.call(app.state.image_provider.slot.release)
        done=wait(c,b,batch['id']);assert len(images)==len(vision)==1 and done['jobs'][0]['repair']['status']=='blocked'


def test_restart_recovers_paid_repair_registration_without_another_image_call(tmp_path,monkeypatch):
    from backend.app import create_app
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report()]);transport=app.state.image_provider.transport;runtime=app.state.pi_runtime.request;original_add=app.state.store.add;failed=[]
    def add(*args,**kwargs):
        if args[2]=='image' and args[4].get('repair_of') and not failed:failed.append(True);raise RuntimeError('synthetic repair registration failure')
        return original_add(*args,**kwargs)
    monkeypatch.setattr(app.state.store,'add',add)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'返修登记重启恢复'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        batch=c.post(b+'/image-batches',json={**request(ps),'inspection':'review_repair'}).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});first=wait(c,b,batch['id'])
        assert first['status']=='needs_attention' and len(images)==2 and first['jobs'][0]['repair']['call']['status']=='completed'
        assert not first['jobs'][0]['repair']['output_id']
    restored=create_app(tmp_path);restored.state.image_provider.transport=transport;monkeypatch.setattr(restored.state.pi_runtime,'request',runtime)
    with TestClient(restored) as c:
        assert len(images)==2 and len(vision)==1
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and len(images)==2 and len(vision)==2
        assert final['jobs'][0]['repair']['call_id']==first['jobs'][0]['repair']['call_id']
        assert final['jobs'][0]['output_id']==first['jobs'][0]['output_id'] and final['jobs'][0]['repair']['output']['adopted']==0
