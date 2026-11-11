"""Synthetic actual-pixel continuity dependencies, never identity/style authority."""
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture
from backend.tests.test_image_batches import packages,request,wait


def link(c,b,package,refs,field='generation_dependencies'):
    response=c.put(b+'/records/'+package['id'],json={'expected_version':package['version'],'content':{**package['content'],field:[{'id':r['id'],'version':r['version']} for r in refs]}})
    assert response.status_code==200,response.text
    return response.json()


def adopt_review(c,b,job):
    adopted=c.post(b+'/candidates/'+job['output_id']+'/adopt',json={})
    assert adopted.status_code==200,adopted.text
    r=adopted.json()
    assert c.post(b+'/records/'+r['id']+'/reviews',json={'version':r['version'],'decision':'approved','note':'合成连续性验收'}).status_code==200
    return r


def test_dependency_waits_for_exact_adopted_reviewed_pixels_and_independent_panel_continues(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'前图连续性'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,3)
        ps[1]=link(c,b,ps[1],[ps[0]])
        # Reading order may differ from execution order; no latest/old-image substitution.
        response=c.post(b+'/image-batches',json=request([ps[1],ps[0],ps[2]]));assert response.status_code==200,response.text
        batch=response.json();assert not calls
        child=batch['jobs'][0];assert child['payload']['dependency_plan']['packages'][0]['id']==ps[0]['id']
        assert child['payload']['dependencies_bound'] is False
        assert '连续性' in child['payload']['prompt']
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert [j['status'] for j in done['jobs']]==['waiting_dependency','succeeded','succeeded'] and len(calls)==2
        # Internal queue cannot bypass the missing actual reference either.
        from fastapi import BackgroundTasks,HTTPException
        with pytest.raises(HTTPException):app.state.image_jobs.queue(pid,child['id'],BackgroundTasks(),batch_id=batch['id'])
        producer=done['jobs'][1];approved=adopt_review(c,b,producer)
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and len(calls)==3,final
        bound=final['jobs'][0];ref=bound['call']['manifest']['references'][-1]
        assert (ref['id'],ref['version'])==(approved['id'],approved['version'])
        assert ref['sha256']==producer['call']['result']['sha256']
        assert bound['call_id']!=child['call_id'] and bound['payload']['preview_call_id']==child['call_id']
        assert c.get(b+'/image-jobs/'+child['id']).json()['output']['adopted']==0
        assert calls[-1].url.path.endswith('/images/edits') and producer['call']['result']['url'].rsplit('/',1)[-1].encode() not in calls[-1].content
        with app.state.store.db() as db:
            original=app.state.image_provider.get(pid,child['call_id'])
            assert original['status']=='prepared' and original['manifest']['references']==[]
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});assert len(calls)==3


@pytest.mark.parametrize('case',['missing','cycle','wrong_version','duplicate','malformed','cross_project'])
def test_invalid_dependency_graph_creates_no_previews(tmp_path,monkeypatch,case):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖图校验'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        if case=='cross_project':
            other=c.post('/api/projects',json={'name':'另项目'}).json()['id'];foreign=packages(c,f'/api/projects/{other}',1)[0]
            ps[1]=link(c,b,ps[1],[foreign])
        elif case=='duplicate':ps[1]=link(c,b,ps[1],[ps[0],ps[0]])
        elif case=='cycle':
            # Set fixed versions before updating so both edges point to final versions.
            ps[0]=link(c,b,ps[0],[{**ps[1],'version':2}]);ps[1]=link(c,b,ps[1],[ps[0]])
        elif case=='malformed':
            ps[1]=c.put(b+'/records/'+ps[1]['id'],json={'expected_version':1,'content':{**ps[1]['content'],'generation_dependencies':[{'episode':1,'panel':1}]}}).json()
        else:ps[1]=link(c,b,ps[1],[{**ps[0],'version':2} if case=='wrong_version' else ps[0]])
        chosen=[ps[1]] if case=='missing' else ps
        response=c.post(b+'/image-batches',json=request(chosen));assert response.status_code in (404,409,422),response.text
        assert not calls and c.get(b+'/image-jobs?kind=image').json()==[]
        assert c.get(b+'/image-batches').json()['total']==0


def test_unreviewed_or_unknown_producer_never_unlocks_child_and_recovery_never_reposts(tmp_path,monkeypatch):
    import httpx
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;attempts=[]
    async def handler(req):
        attempts.append(req)
        if len(attempts)==1:return httpx.Response(500,json={'error':'unknown synthetic'})
        return await original.handle_async_request(req)
    app.state.image_provider.transport=httpx.MockTransport(handler)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'未知依赖'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,3);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id'])
        assert [j['status'] for j in done['jobs']]==['unknown','waiting_dependency','succeeded'] and len(attempts)==2
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});again=wait(c,b,batch['id'])
        assert len(attempts)==2 and again['jobs'][1]['call']['status']=='prepared'
        assert c.post(b+'/image-batches/'+batch['id']+'/cancel',json={}).status_code==200
        assert c.get(b+'/image-batches/'+batch['id']).json()['jobs'][1]['status']=='cancelled'


def test_adoption_without_review_waits_and_regenerated_predecessor_resolves_adopted_target(tmp_path,monkeypatch):
    import io
    from PIL import Image
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'替换前图'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        raw=io.BytesIO();Image.new('RGB',(8,8),'blue').save(raw,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'old.png',raw.getvalue(),'image/png');old=app.state.store.add(db,pid,'image','原第1格',{'episode':1,'panel':1,'url':url},'import')
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id']);root=done['jobs'][0]
        adopted=c.post(b+'/candidates/'+root['output_id']+'/adopt',json={}).json();assert adopted['id']==old['id'] and adopted['version']==2
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});assert wait(c,b,batch['id'])['jobs'][1]['status']=='waiting_dependency' and len(calls)==1
        c.post(b+'/records/'+adopted['id']+'/reviews',json={'version':2,'decision':'approved','note':'新前图审核'})
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id']);assert final['status']=='completed' and len(calls)==2
        ref=final['jobs'][1]['call']['manifest']['references'][0]
        assert ref['id']==old['id'] and ref['version']==2 and ref['sha256']==root['call']['result']['sha256']
        assert raw.getvalue() not in calls[-1].content
        with app.state.store.db() as db:
            path=app.state.store.root/'files'/ref['file_id'];assert path.read_bytes() in calls[-1].content


def test_existing_approved_image_dependency_is_frozen_and_actual_pixels_are_sent(tmp_path,monkeypatch):
    import io
    from PIL import Image
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'已有前图'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,1)
        raw=io.BytesIO();Image.new('RGB',(8,8),'blue').save(raw,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'prior.png',raw.getvalue(),'image/png');prior=app.state.store.add(db,pid,'image','前话图片',{'episode':2,'panel':1,'url':url},'import')
        ps[0]=link(c,b,ps[0],[prior],'previous_image_dependencies')
        assert c.post(b+'/image-batches',json=request(ps)).status_code==409
        c.post(b+'/records/'+prior['id']+'/reviews',json={'version':1,'decision':'approved','note':'固定前图'})
        batch=c.post(b+'/image-batches',json=request(ps)).json();assert batch['jobs'][0]['payload']['dependencies_bound'] is True
        assert len(batch['jobs'][0]['call']['manifest']['references'])==1 and not calls
        c.post(b+'/image-batches/'+batch['id']+'/start',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and raw.getvalue() in calls[0].content


def test_restart_preserves_waiting_edge_and_explicit_recovery_uses_original_producer(tmp_path,monkeypatch):
    from backend.app import create_app
    app,calls=fixture(tmp_path,monkeypatch);transport=app.state.image_provider.transport
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖重启'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id']);assert len(calls)==1
        approved=adopt_review(c,b,done['jobs'][0])
    restored=create_app(tmp_path);restored.state.image_provider.transport=transport
    with TestClient(restored) as c:
        assert c.get(b+'/image-batches/'+batch['id']).json()['jobs'][1]['status']=='waiting_dependency' and len(calls)==1
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and len(calls)==2
        assert final['jobs'][1]['call']['manifest']['references'][-1]['id']==approved['id']


def test_descendant_mock_source_is_visible_in_preview_even_when_only_producer_script_is_mock(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖来源'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        script=c.post(b+'/records',json={'kind':'script','title':'源脚本','content':{'episode':1,'panel':1}}).json()
        c.post(b+'/records/'+script['id']+'/reviews',json={'version':1,'decision':'approved','note':'合成脚本'})
        with app.state.store.db() as db:db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(script['id'],))
        ps[0]=c.put(b+'/records/'+ps[0]['id'],json={'expected_version':1,'content':{**ps[0]['content'],'script_id':script['id'],'script_version':1}}).json()
        ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request([ps[1],ps[0]])).json()
        assert [j['call']['manifest']['source'] for j in batch['jobs']]==['mock','mock'] and not calls


def test_mock_existing_target_provenance_propagates_to_descendant_before_authorization(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'旧图来源依赖'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        with app.state.store.db() as db:app.state.store.add(db,pid,'image','模拟旧格',{'episode':1,'panel':1},'mock')
        batch=c.post(b+'/image-batches',json=request([ps[1],ps[0]])).json()
        assert [j['call']['manifest']['source'] for j in batch['jobs']]==['mock','mock'] and not calls


def test_binding_checkpoint_recovers_same_prepared_call_after_pointer_switch_interruption(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖绑定检查点'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id']);adopt_review(c,b,done['jobs'][0])
        original=app.state.image_provider.prepare;crashed=[]
        def prepare(*args,**kwargs):
            value=original(*args,**kwargs)
            if args[1].startswith('dep:') and not crashed:crashed.append(value['id']);raise RuntimeError('synthetic crash after immutable call saved')
            return value
        monkeypatch.setattr(app.state.image_provider,'prepare',prepare)
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});interrupted=wait(c,b,batch['id'])
        assert interrupted['status']=='interrupted' and len(calls)==1 and crashed
        assert interrupted['jobs'][1]['call_id']==batch['jobs'][1]['call_id']
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['status']=='completed' and len(calls)==2 and final['jobs'][1]['call_id']==crashed[0]
        with app.state.store.db() as db:assert db.execute("SELECT count(*) FROM image_calls WHERE operation_key=?",('dep:'+batch['jobs'][1]['id'],)).fetchone()[0]==1


def test_modified_predecessor_bytes_never_unlock_a_waiting_dependency(tmp_path,monkeypatch):
    import io
    from PIL import Image
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'原像素不可替换'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id']);image=adopt_review(c,b,done['jobs'][0])
        buf=io.BytesIO();Image.new('RGB',(8,8),'green').save(buf,format='PNG')
        fid=image['content']['url'].rsplit('/',1)[-1];(app.state.store.root/'files'/fid).write_bytes(buf.getvalue())
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['jobs'][1]['status']=='waiting_dependency' and len(calls)==1
        assert '原调用返回不一致' in final['jobs'][1]['error']


def test_compiled_dependency_prompt_limit_is_validated_before_any_child_preview(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'连续性编译长度'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b)
        ps[1]=c.put(b+'/records/'+ps[1]['id'],json={'expected_version':1,'content':{**ps[1]['content'],'prompt':'字'*32000}}).json();ps[1]=link(c,b,ps[1],[ps[0]])
        response=c.post(b+'/image-batches',json=request(ps));assert response.status_code==422,response.text
        assert not calls and c.get(b+'/image-jobs?kind=image').json()==[]
        assert c.get(b+'/image-batches').json()['total']==0


def test_missing_predecessor_file_blocks_only_its_branch_during_recovery(tmp_path,monkeypatch):
    from fastapi import BackgroundTasks
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'损坏前图局部分支'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,3);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json()
        # Synthetic checkpoint: host stopped after the root returned, before later dispatch.
        with app.state.store.db() as db:
            db.execute("UPDATE image_batches SET status='running' WHERE id=?",(batch['id'],));app.state.image_batch_control.touch(db,pid,batch['id'])
        background=BackgroundTasks();app.state.image_jobs.queue(pid,batch['jobs'][0]['id'],background,batch_id=batch['id']);c.portal.call(background)
        root=c.get(b+'/image-jobs/'+batch['jobs'][0]['id']).json();image=adopt_review(c,b,root)
        (app.state.store.root/'files'/image['content']['url'].rsplit('/',1)[-1]).unlink()
        with app.state.store.db() as db:db.execute("UPDATE image_batches SET status='interrupted' WHERE id=?",(batch['id'],))
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert [j['status'] for j in final['jobs']]==['succeeded','waiting_dependency','succeeded'] and len(calls)==2,final
        assert '文件' in final['jobs'][1]['error']


def test_changed_producer_package_blocks_waiting_child_even_after_original_pixels_were_approved(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖包版本冻结'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,3);ps[1]=link(c,b,ps[1],[ps[0]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});done=wait(c,b,batch['id']);adopt_review(c,b,done['jobs'][0])
        c.put(b+'/records/'+ps[0]['id'],json={'expected_version':1,'content':{**ps[0]['content'],'prompt':'前格包已改动，需要新确认'}})
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['jobs'][1]['status']=='blocked' and len(calls)==2,final
        assert final['jobs'][2]['status']=='succeeded'


def test_transitive_ancestor_package_change_invalidates_unsent_descendant(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'传递依赖版本'}).json()['id'];b=f'/api/projects/{pid}';ps=packages(c,b,4)
        ps[1]=link(c,b,ps[1],[ps[0]]);ps[2]=link(c,b,ps[2],[ps[1]])
        batch=c.post(b+'/image-batches',json=request(ps)).json();c.post(b+'/image-batches/'+batch['id']+'/start',json={});first=wait(c,b,batch['id']);adopt_review(c,b,first['jobs'][0])
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});second=wait(c,b,batch['id']);adopt_review(c,b,second['jobs'][1]);assert len(calls)==3
        c.put(b+'/records/'+ps[0]['id'],json={'expected_version':1,'content':{**ps[0]['content'],'prompt':'祖先包已更新'}})
        c.post(b+'/image-batches/'+batch['id']+'/recover',json={});final=wait(c,b,batch['id'])
        assert final['jobs'][2]['status']=='blocked' and final['jobs'][3]['status']=='succeeded' and len(calls)==3
        assert final['jobs'][2]['payload']['input_refs'][ps[0]['id']]==1
