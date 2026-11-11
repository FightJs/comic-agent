import asyncio
import json
import pytest
from fastapi import HTTPException
from backend.tests.test_vision_reviews import fixture,result
from backend.graph_documents import import_document,save_parse,get_document
from backend.skills import install
from backend.tests.test_skills import pack


def original(app):
    with app.state.store.db() as db:
        return import_document(app.state.store,db,'p','原著.txt','第一章 归来\n😀林秋穿红衣。\n'.encode())


def source(doc):return {'document_id':doc['id'],'parse_version':1,'start':7,'end':14}


def test_vision_reads_exact_unicode_source_and_review_skill_dependencies(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);doc=original(app);calls=[]
    skill=install(app.state.store,pack(stages=['review'],files={'SKILL.md':'先检查服饰。参照[细则](references/rules.md)。','references/rules.md':'对照原著服饰原文；参考[循环](../SKILL.md)。','unused.md':'不相关的大量资料不自动加载。'}))
    with app.state.store.db() as db:db.execute('INSERT INTO project_skill_settings VALUES(?,?,?)',('p',1,json.dumps([skill['hash']])))
    async def request(command,**kwargs):
        calls.append(kwargs);return {'type':'result','data':{'text':json.dumps({'summary':'按所选原文和规则检查','issues':[]}), 'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    job=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},source_ranges=[source(doc)],operation_key='source')
    assert not calls and job['manifest']['sources'][0]['quote']=='😀林秋穿红衣。'
    assert job['manifest']['sources'][0]['coverage']['complete']
    with app.state.store.db() as db:db.execute('UPDATE project_skill_settings SET revision=2,hashes=?',(json.dumps([]),))
    done=asyncio.run(app.state.vision_reviews.execute('p',job['id']))
    assert done['status']=='completed' and '😀林秋穿红衣。' in calls[0]['prompt']
    assert '先检查服饰' in calls[0]['prompt'] and '对照原著服饰原文' in calls[0]['prompt']
    assert '不相关的大量资料' not in calls[0]['prompt'] and skill['hash'] in calls[0]['prompt']


def test_new_parse_after_vision_preview_blocks_submission_but_keeps_old_quote(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);doc=original(app)
    job=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},source_ranges=[source(doc)],operation_key='parse')
    with app.state.store.db() as db:save_parse(app.state.store,db,'p',doc['id'],'新正文',[{'index':1,'title':'校正版','start':0,'end':3}],[])
    assert app.state.vision_reviews.get('p',job['id'])['stale']
    with pytest.raises(HTTPException):asyncio.run(app.state.vision_reviews.execute('p',job['id']))
    assert app.state.vision_reviews.get('p',job['id'])['manifest']['sources'][0]['quote']=='😀林秋穿红衣。'


@pytest.mark.parametrize('patch',[{'start':-1},{'end':999},{'start':7,'end':7},{'parse_version':99},{'quote':'伪造原文'}])
def test_vision_source_range_cannot_forge_or_escape_original(tmp_path,monkeypatch,patch):
    app,target,_,_=fixture(tmp_path,monkeypatch);doc=original(app)
    with pytest.raises(HTTPException):app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},source_ranges=[{**source(doc),**patch}],operation_key='invalid')


def test_vision_validates_report_citations_against_original_codepoint_offsets(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);doc=original(app);citation={'source':1,'start':8,'end':14,'quote':'林秋穿红衣。'}
    report={'summary':'局部服装检查','issues':[{'severity':'major','category':'costume','description':'衣服不符','evidence':'图1服装与指定原文不符','images':[1],'region':None,'source_evidence':[citation]}]}
    async def request(command,**kwargs):return {'type':'result','data':{'text':json.dumps(report),'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    first=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},source_ranges=[source(doc)],operation_key='citation')
    assert asyncio.run(app.state.vision_reviews.execute('p',first['id']))['status']=='completed'
    citation['quote']='原著写着蓝色衣服'
    second=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},source_ranges=[source(doc)],operation_key='forged')
    done=asyncio.run(app.state.vision_reviews.execute('p',second['id']))
    assert done['status']=='invalid' and done['raw'] and done['report'] is None


def test_vision_http_source_contract_rejects_forgery_and_foreign_novel(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    app,target,_,_=fixture(tmp_path,monkeypatch);doc=original(app)
    with app.state.store.db() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('other','其他项目',0,'t','t'))
        foreign=import_document(app.state.store,db,'other','他书.txt','第一章 他书\n不得跨项目读取。'.encode())
    body={'target':{'id':target['id'],'version':1},'source_ranges':[source(doc)],'submission_id':'api-source'}
    with TestClient(app) as c:
        response=c.post('/api/projects/p/vision-reviews',json=body)
        assert response.status_code==200,response.text
        assert response.json()['manifest']['sources'][0]['quote']=='😀林秋穿红衣。'
        assert c.post('/api/projects/p/vision-reviews',json={**body,'source_ranges':[{**source(doc),'quote':'客户端伪造'}]}).status_code==422
        assert c.post('/api/projects/p/vision-reviews',json={**body,'source_ranges':[{**source(doc),'document_id':foreign['id']}]}).status_code==404
