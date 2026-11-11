"""Isolated UI acceptance server. No real keys, providers, or user project data."""
import copy
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
import backend.app as module
from backend.store import now,dump,uid
from backend import graph_store as gs,graph_documents as docs
class TestVault:
    def get_password(self,*args): return 'isolated-provider-fixture'
    def set_password(self,*args): pass
module.vault=TestVault()
root=Path(__file__).resolve().parents[1]/'output'/'graph-review-data'
app=module.create_app(root)

def provider(req):
    prompt=json.loads(req.content)['messages'][-1]['content']
    if 'TASK:extract' in prompt:
        text=prompt.split('TEXT:\n',1)[1].split('\nORIGINAL_IDENTITIES:',1)[0]
        start=int(re.search(r'start=(\d+)',prompt).group(1))
        names=[n for n in ['阿青','林先生','沈砚','旧院'] if n in text]
        nodes=[]
        for i,name in enumerate(names):
            at=start+text.index(name)
            nodes.append({'id':f'n{i}','label':name,'type':'LOCATION' if name=='旧院' else 'PERSON','evidence':[{'start':at,'end':at+len(name),'quote':name}],'summary':'测试供应商返回的结构化夹具'})
        result={'nodes':nodes,'edges':[],'events':[],'summary':'隔离验收摘要'}
    elif 'consolidate' in prompt: result={'merges':[],'aliases':[]}
    else: result={'summary':'本章记录人物在旧院的相遇，隔离验收夹具。'}
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}],'usage':{'prompt_tokens':80,'completion_tokens':50}})
app.state.graph_transport=httpx.MockTransport(provider)
store=app.state.store
with store.db() as db:
    pid='graph-review'
    if not db.execute('SELECT id FROM projects WHERE id=?',(pid,)).fetchone():
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(pid,'旧院来信 · 图谱验收夹具',0,now(),now()))
        text='第一章 归来\n阿青回到旧院，遇见导师林先生。沈砚是阿青的同伴。\n第二章 来信\n林先生将铜钥匙交给阿青。白鹭会在城中寻找旧院。\n第三章 旧事\n沈砚回忆年少时的相遇。阿青决定守护旧院。'
        doc=docs.import_document(store,db,pid,'旧院来信-测试小说.txt',text.encode(),'auto')
        names=[('阿青','PERSON'),('林先生','PERSON'),('沈砚','PERSON'),('白鹭会','ORGANIZATION'),('旧院','LOCATION'),('铜钥匙','OBJECT'),('城南书院','LOCATION'),('陆行舟','PERSON'),('柳姨','PERSON'),('顾白','PERSON'),('南城','LOCATION'),('青石巷','LOCATION')]
        nodes=[]
        for i,(name,typ) in enumerate(names):
            at=text.find(name); chapter=next((c['index'] for c in doc['chapters'] if c['start']<=at<c['end']),1)
            ev=[{'document_id':doc['id'],'parse_version':1,'chapter':chapter,'start':at,'end':at+len(name),'quote':name}] if at>=0 else []
            n=gs.node({'id':f'n{i}','label':name,'type':typ,'aliases':['青儿'] if i==0 else [],'summary':['重返旧院的年轻旅人，正在追寻一封来信的主人。','阿青的导师，守护旧院多年。','阿青的同伴，熟悉南城街巷。'][i%3],'important':i<3,'attributes':{'身份':'旅人' if i==0 else '故事角色','性格':'坚定、细致'},'known_from':chapter,'evidence':ev,'states':[{'id':f's{i}','label':'日常装' if typ=='PERSON' else '常态','attributes':{'服装':'待资产设计补全'} if typ=='PERSON' else {},'known_from':chapter,'assets':[]}]},manual=False)
            n['_known']={'summary':chapter,'aliases':{'青儿':1},'attributes':{'身份':chapter,'性格':chapter}}
            nodes.append(n)
        pairs=[(0,1,'师徒',False),(0,2,'同行',False),(0,4,'归来',False),(1,4,'守护',False),(3,4,'寻找',True),(1,5,'保管',False),(0,5,'获得',False),(2,10,'熟悉',False),(6,1,'任教',False),(7,3,'成员',False),(8,0,'关照',False),(9,7,'同伴',False),(10,11,'包含',False),(0,1,'信任',True)]
        edges=[gs.edge({'id':f'e{i}','source':f'n{a}','target':f'n{b}','relation':label,'inferred':inf,'reason':'角色行为暗示，待人工核对' if inf else '', 'known_from':1,'story_time':'故事当前','evidence':nodes[a]['evidence']}) for i,(a,b,label,inf) in enumerate(pairs)]
        state=gs.empty();state['original']={'nodes':nodes,'edges':edges};state['adaptation']=copy.deepcopy(state['original']);gs.publish(store,db,pid,state,'隔离验收图谱夹具')
        store.add(db,pid,'outline','当前细纲 · 测试',{'html':'<h2>第1话 归来</h2><p>阿青回到旧院，见到林先生。</p><h2>第2话 来信</h2><p>沈砚陪同阿青出发。</p>'},'manual')
    db.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content',(dump({'text':{'purpose':'text','url':'https://graph-test.invalid/v1','model':'isolated-fixture'}}),))
# Independent UI reviewer may confirm this safe local fixture without real providers.
with store.db() as db:
    if not db.execute("SELECT id FROM records WHERE project_id=? AND title='图谱审核 · 可确认资产夹具'",(pid,)).fetchone():
        import io
        from PIL import Image,ImageDraw
        image=Image.new('RGB',(320,400),'#e9e3d7'); draw=ImageDraw.Draw(image)
        draw.ellipse((113,45,207,140),fill='#d4ac87');draw.rectangle((88,145,232,350),fill='#3e6b68')
        output=io.BytesIO();image.save(output,'PNG'); raw=output.getvalue()
        style_url=store.file(db,pid,'审核画风夹具.png',raw,'image/png')
        style=store.add(db,pid,'style','图谱审核 · 当前画风夹具',{'url':style_url,'width':320,'height':400,'description':'隔离本地验收画风'},'import')
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),style['id'],1,'approved','隔离验收精确版本已核验','import',now()))
        db.execute("INSERT INTO selections VALUES(?,?,?,?) ON CONFLICT(project_id,kind) DO UPDATE SET record_id=excluded.record_id,version=excluded.version",(pid,'style',style['id'],1))
        asset_url=store.file(db,pid,'阿青-日常装-审核夹具.png',raw,'image/png')
        asset=store.add(db,pid,'asset','图谱审核 · 可确认资产夹具',{'url':asset_url,'width':320,'height':400,'entity_id':'n0','state_id':'s0','category':'人物','characters':'阿青','state':'日常装','visual_fields':{'服装':'青色外衣','发型':'黑发束起'},'style_reference':{'record_id':style['id'],'version':1,'source':'import'}},'import')
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),asset['id'],1,'approved','隔离验收精确版本已核验','import',now()))

with store.db() as db:
    if not db.execute("SELECT id FROM records WHERE project_id=? AND title='图谱审核 · 未绑定资产夹具'",(pid,)).fetchone():
        style=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
        source=db.execute("SELECT id FROM records WHERE project_id=? AND title='图谱审核 · 可确认资产夹具'",(pid,)).fetchone()
        asset=store.get(db,pid,source['id'])
        content={k:v for k,v in asset['content'].items() if k not in ('entity_id','state_id')}
        content['style_reference']={**dict(style),'source':'import'}
        unbound=store.add(db,pid,'asset','图谱审核 · 未绑定资产夹具',content,'import')
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),unbound['id'],1,'approved','隔离验收未绑定精确版本','import',now()))

if __name__=='__main__': uvicorn.run(app,host='127.0.0.1',port=8771)
