import json
import pytest
from fastapi import HTTPException
from backend.app import create_app
from backend.agent_tools import freeze_context
from backend.agent_changes import schema,propose,adopt
from backend import graph_store as gs


def setup(tmp_path,kind='script',content=None,source='manual'):
    app=create_app(tmp_path);store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','项目',0,'t','t')");schema(db)
        r=store.add(db,'p',kind,'待修改',content or {'episode':2,'panel':7,'batch':1,'description':'旧画面'},source)
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage=kind)
        frozen['write_refs']=[{'id':r['id'],'version':1}];frozen['stage']=kind
        db.execute("INSERT INTO agent_runs VALUES('run','p','session','running','意见','','',NULL,'t','t')")
    return store,r,frozen


def test_proposal_does_not_mutate_until_adoption_and_preserves_identity(tmp_path):
    store,r,frozen=setup(tmp_path)
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'调整画面','changes':[{'target':'record','id':r['id'],'patch':{'description':'雨夜重逢'}}]})
        assert store.get(db,'p',r['id'])['version']==1
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        result=adopt(store,db,'p',p['id'])
        current=store.get(db,'p',r['id'])
        assert current['content']['description']=='雨夜重逢'
        assert current['content']['panel']==7 and current['content']['episode']==2
        assert current['version']==2 and current['review']=='pending'
        assert adopt(store,db,'p',p['id'])==result


def test_proposal_rejects_identity_fields_unselected_targets_and_cross_project(tmp_path):
    store,r,frozen=setup(tmp_path)
    with store.db() as db:
        for patch in [{'panel':8},{'review':'approved'},{'url':'https://invalid'},{'description':{'not':'text'}}]:
            with pytest.raises(HTTPException):propose(store,db,'p','run',frozen,{'title':'x','changes':[{'target':'record','id':r['id'],'patch':patch}]})
        frozen['write_refs']=[]
        with pytest.raises(HTTPException):propose(store,db,'p','run',frozen,{'title':'x','changes':[{'target':'record','id':r['id'],'patch':{'description':'x'}}]})


def test_stale_adoption_is_atomic_and_mock_lineage_is_kept(tmp_path):
    store,r,frozen=setup(tmp_path,source='mock')
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'x','changes':[{'target':'record','id':r['id'],'patch':{'description':'候选'}}]})
        store.save(db,'p',r['id'],1,{'description':'已有人改过','panel':7,'episode':2,'batch':1})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        with pytest.raises(HTTPException) as error:adopt(store,db,'p',p['id'])
        assert error.value.status_code==409 and store.get(db,'p',r['id'])['content']['description']=='已有人改过'


def test_doc_text_updates_html_without_leaving_stale_text_shadow(tmp_path):
    store,r,frozen=setup(tmp_path,'outline',{'text':'旧细纲'})
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'新细纲','changes':[{'target':'record','id':r['id'],'patch':{'text':'第1话\n新细纲<script>'}}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id']);content=store.get(db,'p',r['id'])['content']
        assert 'text' not in content and '&lt;script&gt;' in content['html']


def test_graph_node_proposal_uses_frozen_revision_and_preserves_original_layer(tmp_path):
    store,_,frozen=setup(tmp_path)
    with store.db() as db:
        state=gs.empty();state['original']['nodes']=[gs.node({'id':'n','label':'林秋','summary':'旧描述'})]
        rev=gs.publish(store,db,'p',state,'原始图谱')
        frozen.update(stage='memory',graph_revision=rev,write_refs=[])
        p=propose(store,db,'p','run',frozen,{'title':'改节点','changes':[{'target':'graph_node','id':'n','patch':{'summary':'新的节点描述'}}]})
        assert gs.load(store,db,'p')[0]==rev
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id']);_,latest=gs.load(store,db,'p')
        assert latest['adaptation']['nodes'][0]['summary']=='新的节点描述'
        assert latest['original']['nodes'][0]['summary']=='旧描述'
        from backend.agent_tools import ProjectTools
        current=freeze_context(store,db,'p',stage='memory')
    assert ProjectTools(store,'p',current).call('project_query',{'action':'graph','id':'n'})['nodes'][0]['summary']=='新的节点描述'


def test_mock_adoption_stays_mock_and_active_runs_cannot_adopt(tmp_path):
    store,r,frozen=setup(tmp_path,source='mock')
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'x','changes':[{'target':'record','id':r['id'],'patch':{'description':'新候选'}}]})
        with pytest.raises(HTTPException):adopt(store,db,'p',p['id'])
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id'])
        assert store.get(db,'p',r['id'])['source']=='mock'


def test_package_parts_do_not_overwrite_a_manual_full_prompt(tmp_path):
    store,r,frozen=setup(tmp_path,'package',{'prompt':'人工完整覆盖','prompt_mode':'override','shot_prompt':'旧镜头','episode':1,'panel':1,'batch':1})
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'镜头建议','changes':[{'target':'record','id':r['id'],'patch':{'shot_prompt':'新的镜头要求'}}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id']);result=store.get(db,'p',r['id'])
        assert result['content']['prompt']=='人工完整覆盖' and result['content']['shot_prompt']=='新的镜头要求'


def test_mock_large_record_read_taints_a_candidate_for_manual_target(tmp_path):
    from backend.agent_tools import ProjectTools
    store,r,_=setup(tmp_path)
    with store.db() as db:
        mock=store.add(db,'p','outline','模拟参考',{'text':'模拟'*20000},'mock')
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage='script');frozen.update(stage='script',write_refs=[{'id':r['id'],'version':1}])
    output=ProjectTools(store,'p',frozen).call('project_query',{'action':'record','id':mock['id']})
    assert output['source']=='mock'
    with store.db() as db:
        db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',('run','read','project_query','hash',json.dumps(output),'t'))
        p=propose(store,db,'p','run',frozen,{'title':'根据模拟参考改稿','changes':[{'target':'record','id':r['id'],'patch':{'description':'新稿'}}]})
        assert db.execute('SELECT source FROM agent_proposals WHERE id=?',(p['id'],)).fetchone()[0]=='mock'


def test_http_tool_proposal_is_separate_then_explicit_adoption_is_idempotent(tmp_path,monkeypatch):
    import time
    import backend.app as app_module
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module.vault,'get_password',lambda *args:'fixture-only')
    app=create_app(tmp_path);original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='run':return await original(command,**kwargs)
        message={'name':'propose_changes','tool_call_id':'write-plan','input_hash':'a'*64,'arguments':{'title':'雨夜镜头','changes':[{'target':'record','id':record['id'],'patch':{'description':'雨夜重逢'}}]}}
        response=await kwargs['on_tool'](message)
        assert await kwargs['on_tool'](message)==response
        with pytest.raises(HTTPException):await kwargs['on_tool']({**message,'input_hash':'b'*64})
        assert response['status']=='pending'
        return {'type':'result','data':{'text':'已提交修改候选，尚未改动成品。'}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'HTTP编辑闭环'}).json()['id'];base=f'/api/projects/{pid}'
        record=c.post(base+'/records',json={'kind':'script','title':'第2话第7格','content':{'episode':2,'panel':7,'batch':1,'description':'旧稿'}}).json()
        with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':'http://127.0.0.1/fixture','model':'fixture'}}),))
        ref={'id':record['id'],'version':1}
        assert c.post(base+'/agent/sessions',json={'stage':'script','refs':[ref,ref]}).status_code==422
        sid=c.post(base+'/agent/sessions',json={'stage':'script','refs':[ref]}).json()['id']
        sent=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'调整画面','expected_version':0});assert sent.status_code==200,sent.text
        rid=sent.json()['id'];deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=c.get(base+f'/agent/runs/{rid}').json()
            if result['status']=='completed':break
            time.sleep(.02)
        assert result['status']=='completed',result
        assert len(result['proposals'])==1 and result['tool_calls']==1
        proposal=result['proposals'][0]['id'];path=base+'/agent/proposals/'+proposal
        assert c.get(base+'/records/'+record['id']).json()['version']==1
        assert c.get(path).json()['changes'][0]['before']['description']=='旧稿'
        other=c.post('/api/projects',json={'name':'隔离'}).json()['id']
        assert c.get(f'/api/projects/{other}/agent/proposals/{proposal}').status_code==404
        adopted=c.post(path+'/adopt',json={});assert adopted.status_code==200,adopted.text
        assert c.post(path+'/adopt',json={}).json()==adopted.json()
        final=c.get(base+'/records/'+record['id']).json()
        assert final['version']==2 and final['source']=='ai' and final['content']['panel']==7
        rebound=c.put(base+f'/agent/sessions/{sid}/refs',json={'expected_version':1,'refs':[{'id':record['id'],'version':2}]})
        assert rebound.status_code==200,rebound.text
        assert rebound.json()['version']==2 and rebound.json()['message_count']==1


def test_one_stale_target_prevents_all_records_in_a_proposal_from_changing(tmp_path):
    store,first,_=setup(tmp_path)
    with store.db() as db:
        second=store.add(db,'p','script','第2格',{'episode':2,'panel':8,'batch':1,'description':'第二格原稿'})
        refs=[{'id':first['id'],'version':1},{'id':second['id'],'version':1}]
        frozen=freeze_context(store,db,'p',refs,stage='script');frozen.update(stage='script',write_refs=refs)
        p=propose(store,db,'p','run',frozen,{'title':'两格统一修改','changes':[{'target':'record','id':r['id'],'patch':{'description':'候选内容'}} for r in (first,second)]})
        store.save(db,'p',second['id'],1,{**second['content'],'description':'手动更新'})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        with pytest.raises(HTTPException):adopt(store,db,'p',p['id'])
        assert store.get(db,'p',first['id'])['version']==1
        assert store.get(db,'p',second['id'])['content']['description']=='手动更新'


@pytest.mark.parametrize('patch,status',[
    ({'aliases':'不是列表'},422),({'attributes':[]},422),({'important':1},422),({'type':'INVALID'},422),({'evidence':[]},403),({'attributes':{'年龄':'青年'}},None),({'aliases':['林少侠'],'important':True},None),
])
def test_graph_candidate_fields_have_strict_types_and_protected_evidence(tmp_path,patch,status):
    store,_,frozen=setup(tmp_path)
    with store.db() as db:
        state=gs.empty();state['original']['nodes']=[gs.node({'id':'n','label':'林秋'})]
        revision=gs.publish(store,db,'p',state,'图谱');frozen.update(stage='memory',graph_revision=revision,write_refs=[])
        body={'title':'节点候选','changes':[{'target':'graph_node','id':'n','patch':patch}]}
        if status:
            with pytest.raises(HTTPException) as error:propose(store,db,'p','run',frozen,body)
            assert error.value.status_code==status
        else:assert propose(store,db,'p','run',frozen,body)['status']=='pending'


def test_graph_relationship_candidate_keeps_endpoints_and_original_evidence_layer(tmp_path):
    store,_,frozen=setup(tmp_path)
    with store.db() as db:
        state=gs.empty();state['original']['nodes']=[gs.node({'id':'a','label':'林秋'}),gs.node({'id':'b','label':'沈宁'})]
        state['original']['edges']=[gs.edge({'id':'edge','source':'a','target':'b','relation':'旧关系'})]
        revision=gs.publish(store,db,'p',state,'关系图谱');frozen.update(stage='memory',graph_revision=revision,write_refs=[])
        p=propose(store,db,'p','run',frozen,{'title':'补充关系说明','changes':[{'target':'graph_edge','id':'edge','patch':{'relation':'同门','inferred':True,'reason':'依据双方叙述，仍待核对'}}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id']);_,result=gs.load(store,db,'p')
        assert result['adaptation']['edges'][0]['relation']=='同门'
        assert result['adaptation']['edges'][0]['source']=='a' and result['adaptation']['edges'][0]['target']=='b'
        assert result['original']['edges'][0]['relation']=='旧关系'


@pytest.mark.parametrize('flags',[
    {'creation_candidate':True},
    {'candidate_for':'original','input_version':1},
    {'pending_for':'original'},
    {'rejected':True},
])
def test_ai_text_edit_does_not_promote_a_production_candidate(tmp_path,flags):
    from backend.store import is_primary
    store,r,frozen=setup(tmp_path,content={'episode':2,'panel':7,'description':'待决稿',**flags})
    with store.db() as db:
        db.execute('UPDATE records SET adopted=0 WHERE id=?',(r['id'],))
        p=propose(store,db,'p','run',frozen,{'title':'只修改措辞','changes':[{'target':'record','id':r['id'],'patch':{'description':'修改后的待决稿'}}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        result=adopt(store,db,'p',p['id'])
        current=store.get(db,'p',r['id'])
        assert current['content']['description']=='修改后的待决稿'
        assert current['adopted']==0
        assert not is_primary(current)
        assert all(current['content'][key]==value for key,value in flags.items())
        assert adopt(store,db,'p',p['id'])==result


def test_script_create_is_explicit_versioned_and_does_not_renumber(tmp_path):
    store,r,frozen=setup(tmp_path)
    body={'title':'增加反应镜头','changes':[{'target':'script_create','id':r['id'],'patch':{'panel':8,'description':'停顿后回头','dialogue':'谁在那里？'}}]}
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,body)
        assert db.execute("SELECT count(*) FROM records WHERE kind='script'").fetchone()[0]==1
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        result=adopt(store,db,'p',p['id'])
        created=store.get(db,'p',result['records'][0]['id'])
        assert created['content']['episode']==2 and created['content']['panel']==8 and created['content']['batch']==1
        assert created['content']['description']=='停顿后回头' and created['source']=='ai'
        assert created['review']=='pending' and created['adopted']==1
        assert store.get(db,'p',r['id'])['version']==1
        assert adopt(store,db,'p',p['id'])==result


def test_script_delete_retires_downstream_and_preserves_history(tmp_path):
    from backend.store import is_primary
    store,r,_=setup(tmp_path)
    with store.db() as db:
        package=store.add(db,'p','package','包',{'episode':2,'panel':7,'prompt':'提示词'})
        image=store.add(db,'p','image','图',{'episode':2,'panel':7,'url':'old.png'})
        trial=store.add(db,'p','trial','确认',{'references':[{'id':image['id'],'version':1}]})
        other=store.add(db,'p','script','另一格',{'episode':2,'panel':8,'description':'保留'})
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage='script');frozen.update(stage='script',write_refs=[{'id':r['id'],'version':1}])
        p=propose(store,db,'p','run',frozen,{'title':'删重复镜头','changes':[{'target':'script_delete','id':r['id'],'patch':{'reason':'重复信息'}}]})
        assert store.get(db,'p',image['id'])['version']==1
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id'])
        for item in (r,package,image,trial):
            current=store.get(db,'p',item['id'])
            assert current['version']==2 and not is_primary(current)
            assert current['content']['deleted_by_script']==r['id']
            assert store.get(db,'p',item['id'],1)['content']==item['content']
        assert is_primary(store.get(db,'p',other['id']))


def test_script_structural_candidate_rejects_changed_dependencies_and_duplicates(tmp_path):
    store,r,frozen=setup(tmp_path)
    with store.db() as db:
        p=propose(store,db,'p','run',frozen,{'title':'新增','changes':[{'target':'script_create','id':r['id'],'patch':{'panel':8,'description':'新格'}}]})
        store.add(db,'p','script','同时新增',{'episode':2,'panel':8,'description':'他人稿'})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        with pytest.raises(HTTPException) as error:adopt(store,db,'p',p['id'])
        assert error.value.status_code==409
        assert db.execute("SELECT count(*) FROM records WHERE kind='script'").fetchone()[0]==2


@pytest.mark.parametrize('target,patch',[
    ('script_create',{'panel':7,'description':'重复格号'}),
    ('script_create',{'panel':True,'description':'非法格号'}),
    ('script_create',{'panel':8,'episode':3,'description':'越界'}),
    ('script_delete',{'reason':''}),
    ('script_delete',{'reason':'删格','panel':9}),
])
def test_script_structural_changes_validate_identity_and_reason(tmp_path,target,patch):
    store,r,frozen=setup(tmp_path)
    with store.db() as db:
        with pytest.raises(HTTPException):propose(store,db,'p','run',frozen,{'title':'越界','changes':[{'target':target,'id':r['id'],'patch':patch}]})


def test_deleted_script_dependencies_cannot_be_resurrected_by_normal_save_or_image_adopt(tmp_path):
    from fastapi.testclient import TestClient
    app=create_app(tmp_path);store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','项目',0,'t','t')")
        script=store.add(db,'p','script','已删格',{'episode':1,'panel':1,'deleted_by_script':'script'})
        image=store.add(db,'p','image','撤下图片',{'episode':1,'panel':1,'url':'old.png','deleted_by_script':script['id']})
        db.execute('UPDATE records SET adopted=0')
    with TestClient(app) as client:
        response=client.post(f"/api/projects/p/records/{image['id']}/adopt",json={'version':1})
        assert response.status_code==409
        with store.db() as db:
            with pytest.raises(HTTPException):store.save(db,'p',script['id'],1,{'episode':1,'panel':1})


def test_script_create_does_not_reuse_orphan_downstream_identity(tmp_path):
    store,r,_=setup(tmp_path)
    with store.db() as db:
        store.add(db,'p','package','旧包',{'episode':2,'panel':8,'prompt':'旧输入'})
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage='script');frozen.update(stage='script',write_refs=[{'id':r['id'],'version':1}])
        with pytest.raises(HTTPException) as error:
            propose(store,db,'p','run',frozen,{'title':'新格','changes':[{'target':'script_create','id':r['id'],'patch':{'panel':8,'description':'新画面'}}]})
        assert error.value.status_code==409


def test_script_delete_dependency_drift_blocks_whole_proposal(tmp_path):
    store,r,_=setup(tmp_path)
    with store.db() as db:
        package=store.add(db,'p','package','旧包',{'episode':2,'panel':7,'prompt':'旧稿'})
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage='script');frozen.update(stage='script',write_refs=[{'id':r['id'],'version':1}])
        p=propose(store,db,'p','run',frozen,{'title':'删除','changes':[{'target':'script_delete','id':r['id'],'patch':{'reason':'重复'}}]})
        store.save(db,'p',package['id'],1,{**package['content'],'prompt':'人工新稿'})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        with pytest.raises(HTTPException) as error:adopt(store,db,'p',p['id'])
        assert error.value.status_code==409
        assert store.get(db,'p',r['id'])['version']==1
        assert store.get(db,'p',package['id'])['content']['prompt']=='人工新稿'


def test_script_delete_follows_explicit_downstream_references(tmp_path):
    store,r,_=setup(tmp_path)
    with store.db() as db:
        package=store.add(db,'p','package','历史链接包',{'episode':9,'panel':9,'script_id':r['id']})
        image=store.add(db,'p','image','历史链接图',{'episode':9,'panel':9,'package_id':package['id']})
        frozen=freeze_context(store,db,'p',[{'id':r['id'],'version':1}],stage='script');frozen.update(stage='script',write_refs=[{'id':r['id'],'version':1}])
        p=propose(store,db,'p','run',frozen,{'title':'删除','changes':[{'target':'script_delete','id':r['id'],'patch':{'reason':'重复'}}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        adopt(store,db,'p',p['id'])
        assert store.get(db,'p',package['id'])['adopted']==0
        assert store.get(db,'p',image['id'])['adopted']==0
