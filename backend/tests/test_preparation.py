from backend.tests.test_api import client, project, record


def test_style_sequence_and_frozen_asset(client):
    p = project(client)
    url = f'/api/projects/{p}'
    assert client.post(url+'/tasks', json={'kind':'asset'}).status_code == 409
    style = record(client,p,'style',{'characters':'同一人物','scene':'同一场景'},source='mock')
    assert client.post(url+'/style-selection',json={'record_id':style['id'],'version':1}).status_code == 200
    assert client.get(url+'/style-selection').json()['status'] == 'confirmed'
    job = client.post(url+'/tasks',json={'kind':'asset'}).json()
    tasks = client.get(url+'/tasks').json()
    task = next(t for t in tasks if t['id']==job['id'])
    asset = client.get(url+'/records/'+task['output_id']).json()
    assert asset['content']['style_reference'] == {'record_id':style['id'],'version':1,'source':'mock'}
    assert not client.get(url+'/gates').json()['ready']
    client.put(url+'/records/'+style['id'],json={'expected_version':1,'content':{'characters':'新版本'}})
    assert client.get(url+'/style-selection').json()['status'] == 'stale'
    assert client.post(url+'/style-selection',json={'record_id':style['id'],'version':1}).status_code == 409
    assert client.post(url+'/tasks',json={'kind':'asset'}).status_code == 409
    assert client.get(url+'/records/'+asset['id']).json()['content']['style_reference']['version'] == 1


def test_style_selection_is_project_scoped(client):
    p,q=project(client),project(client)
    style=record(client,p,'style')
    assert client.post(f'/api/projects/{q}/style-selection',json={'record_id':style['id'],'version':1}).status_code == 404


def test_late_asset_keeps_original_style_and_reconfirmation_resets_review(client, monkeypatch):
    import asyncio
    original_sleep=asyncio.sleep
    p=project(client)
    url=f'/api/projects/{p}'
    first=record(client,p,'style',source='mock')
    second=record(client,p,'style',source='mock')
    client.post(url+'/style-selection',json={'record_id':first['id'],'version':1})
    async def switch_while_running(_):
        with client.app.state.store.db() as db:
            db.execute("UPDATE selections SET record_id=? WHERE project_id=? AND kind='style'",(second['id'],p))
    from types import SimpleNamespace
    monkeypatch.setattr('backend.app.asyncio',SimpleNamespace(sleep=switch_while_running))
    assert asyncio.sleep is original_sleep, '模拟任务测试不能替换图谱后台等全局协程的等待函数'
    tid=client.post(url+'/tasks',json={'kind':'asset'}).json()['id']
    task=next(t for t in client.get(url+'/tasks').json() if t['id']==tid)
    asset=client.get(url+'/records/'+task['output_id']).json()
    assert asset['content']['style_reference']['record_id']==first['id']
    client.post(url+'/records/'+asset['id']+'/reviews',json={'version':1,'decision':'approved','note':'旧画风审核'})
    rebound=client.post(url+'/records/'+asset['id']+'/confirm-style',json={'version':1}).json()
    assert rebound['version']==2 and rebound['review']=='pending' and rebound['source']=='mock'
    assert rebound['content']['style_reference']['record_id']==second['id']
    assert client.post(url+'/records/'+asset['id']+'/confirm-style',json={'version':1}).status_code==409
    old=client.get(url+'/records/'+asset['id']+'/versions').json()
    assert any(v['content']['style_reference']['record_id']==first['id'] for v in old)


def test_three_styles_share_representative_set_with_two_samples(client):
    p=project(client)
    url=f'/api/projects/{p}'
    for panel in range(1,4):
        assert client.post(url+'/tasks',json={'kind':'style','panel':panel}).status_code==200
    rows=client.get(url+'/records').json()
    assert len(rows)==3
    assert all(r['content']['representative_set']==rows[0]['content']['representative_set'] for r in rows)
    assert all(len(r['content']['samples'])==2 and r['source']=='mock' for r in rows)


def test_switching_back_does_not_restore_old_asset_approval(client):
    p=project(client); url=f'/api/projects/{p}'
    a,b=record(client,p,'style'),record(client,p,'style')
    client.post(url+'/style-selection',json={'record_id':a['id'],'version':1})
    asset=record(client,p,'asset',{'style_reference':{'record_id':a['id'],'version':1,'source':'manual'}})
    client.post(url+'/records/'+asset['id']+'/reviews',json={'version':1,'decision':'approved','note':'通过'})
    for style in [b,a]: client.post(url+'/style-selection',json={'record_id':style['id'],'version':1})
    assert client.get(url+'/records/'+asset['id']).json()['review']!='approved'
