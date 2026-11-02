import asyncio
import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import keyring
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from .store import Store, uid, now, dump
from .simulation import content_for, demo_image


class MacVault:
    def backend(self):
        backend=keyring.get_keyring()
        if not type(backend).__module__.startswith('keyring.backends.macOS'):
            raise RuntimeError('仅允许 macOS 钥匙串后端')
        return backend
    def get_password(self,*args): return self.backend().get_password(*args)
    def set_password(self,*args): return self.backend().set_password(*args)

vault = MacVault()
KINDS = Literal['original','memory','skeleton','outline','style','asset','script','package','image','trial']

class ProjectIn(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    archived: bool = False
class RecordIn(BaseModel):
    kind: KINDS
    title: str = Field(min_length=1,max_length=200)
    content: dict = Field(default_factory=dict)
    source: Literal['manual','mock'] = 'manual'
class SaveIn(BaseModel):
    expected_version: int = Field(ge=1)
    content: dict
    title: str | None = None
class ReviewIn(BaseModel):
    version: int = Field(ge=1)
    decision: Literal['approved','changes']
    note: str = Field(max_length=10000)
class AnnotationIn(BaseModel):
    expected_version: int = Field(ge=0)
    image_version: int = Field(ge=1)
    items: list[dict] = Field(max_length=500)
class TaskIn(BaseModel):
    kind: Literal['memory','skeleton','outline','script','package','style','asset','image','repair']
    target_id: str | None = None
    input_version: int | None = None
    base_image_version: int | None = None
    instruction: str = Field(default='',max_length=10000)
    batch: int = Field(default=1,ge=1)
    episode: int = Field(default=1,ge=1)
    panel: int = Field(default=1,ge=1)
    fail: bool = False
class AdoptIn(BaseModel):
    version: int = Field(ge=1)
class DownloadIn(BaseModel):
    ids: list[str] = Field(min_length=1,max_length=100)
class SelectionIn(BaseModel):
    record_id: str
    version: int = Field(ge=1)
class BatchReviewIn(BaseModel):
    batch: int = Field(ge=1)
    records: list[dict] = Field(min_length=1,max_length=1000)
    decision: Literal['approved','changes']
    note: str = Field(max_length=10000)

class SettingsIn(BaseModel):
    url: str = Field(default='',max_length=2000)
    model: str = Field(default='',max_length=200)
    purpose: Literal['text','image','vision'] = 'text'
    secret: str | None = Field(default=None,max_length=10000)


def create_app(data_dir=None):
    store=Store(data_dir or os.environ.get('COMIC_DATA_DIR',Path(__file__).resolve().parents[1]/'data'))
    app=FastAPI(title='条漫 Agent 本地 API')
    app.state.store=store

    @app.exception_handler(RequestValidationError)
    async def validation_error(request:Request,exc:RequestValidationError):
        # Pydantic's default response includes rejected input, including credentials.
        return JSONResponse({'detail':'输入格式无效，请检查必填项、字段类型和长度。'},status_code=422)

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin=request.headers.get('origin')
        host=request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
        if origin and urlparse(origin).hostname not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'拒绝跨站请求'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/api/health')
    def health(): return {'ok':True,'ai_connected':False}

    @app.get('/api/projects')
    def projects():
        with store.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY updated DESC')]

    @app.post('/api/projects')
    def create_project(body:ProjectIn):
        name=body.name.strip()
        if not name: raise HTTPException(422,'项目名称不能为空')
        with store.db() as db:
            pid,stamp=uid(),now()
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(pid,name,0,stamp,stamp))
            return store.project(db,pid)

    @app.put('/api/projects/{pid}')
    def update_project(pid:str,body:ProjectIn):
        with store.db() as db:
            store.project(db,pid)
            if not body.name.strip(): raise HTTPException(422,'项目名称不能为空')
            db.execute('UPDATE projects SET name=?,archived=?,updated=? WHERE id=?',(body.name.strip(),body.archived,now(),pid))
            return store.project(db,pid)

    @app.get('/api/projects/{pid}/records')
    def records(pid:str,kind:str|None=None):
        with store.db() as db:
            store.project(db,pid)
            rows=db.execute('SELECT id FROM records WHERE project_id=? ORDER BY created',(pid,)).fetchall()
            values=[store.get(db,pid,r['id']) for r in rows]
            return [r for r in values if kind is None or r['kind']==kind]

    def validate_content(db,pid,kind,content):
        for reference in content.get('references',[]):
            if not isinstance(reference,dict) or not reference.get('id'): raise HTTPException(422,'参考需包含资产标识')
            store.get(db,pid,reference['id'],reference.get('version'))
        if kind in ('asset','style','image') and content.get('url'):
            fid=content['url'].split('/')[-1]
            if content['url']!=f'/api/projects/{pid}/files/{fid}' or not db.execute('SELECT id FROM files WHERE id=? AND project_id=?',(fid,pid)).fetchone():
                raise HTTPException(422,'图片必须来自当前项目导入文件')
        if kind in ('script','package','image'):
            for field in ('batch','episode','panel'):
                value=content.get(field,1)
                if not isinstance(value,int) or value < 1: raise HTTPException(422,'话格编号需为正整数')

    def inherited_source(db,pid,content,source):
        if content.get('script_id'):
            script=store.get(db,pid,content['script_id'],content.get('script_version'))
            if script['kind']!='script': raise HTTPException(422,'脚本引用类型无效')
            if script['source']=='mock': source='mock'
        for reference in content.get('references',[]):
            if store.get(db,pid,reference['id'],reference.get('version'))['source']=='mock': return 'mock'
        return source

    @app.post('/api/projects/{pid}/records')
    def create_record(pid:str,body:RecordIn):
        if body.kind=='original': raise HTTPException(422,'原著请通过 TXT 导入')
        with store.db() as db:
            validate_content(db,pid,body.kind,body.content)
            return store.add(db,pid,body.kind,body.title,body.content,inherited_source(db,pid,body.content,body.source))

    @app.get('/api/projects/{pid}/records/{rid}')
    def record(pid:str,rid:str,version:int|None=None):
        with store.db() as db: return store.get(db,pid,rid,version)

    @app.put('/api/projects/{pid}/records/{rid}')
    def save_record(pid:str,rid:str,body:SaveIn):
        with store.db() as db:
            old=store.get(db,pid,rid)
            if old['kind']=='original': raise HTTPException(422,'原著只读，请导入新文件')
            validate_content(db,pid,old['kind'],body.content)
            if old['kind'] in ('script','package','image'):
                for key in ('batch','episode','panel'):
                    if key in old['content'] and body.content.get(key)!=old['content'][key]: raise HTTPException(422,'源话格身份不可修改')
            if old['kind'] in ('asset','style','image'):
                for key in ('url','width','height'):
                    if old['content'].get(key)!=body.content.get(key): raise HTTPException(422,'更换图片请使用图片导入入口')
            return store.save(db,pid,rid,body.expected_version,body.content,body.title,inherited_source(db,pid,body.content,'manual'))

    @app.post('/api/projects/{pid}/records/{rid}/mock-edit')
    def mock_edit(pid:str,rid:str,body:SaveIn):
        with store.db() as db:
            old=store.get(db,pid,rid)
            if old['kind'] not in ('skeleton','outline'): raise HTTPException(422,'只支持文档选段修改')
            return store.save(db,pid,rid,body.expected_version,body.content,source='mock')

    @app.get('/api/projects/{pid}/records/{rid}/versions')
    def versions(pid:str,rid:str):
        with store.db() as db:
            store.get(db,pid,rid)
            return [store.get(db,pid,rid,r['version']) for r in db.execute('SELECT version FROM versions WHERE record_id=? ORDER BY version DESC',(rid,))]

    @app.get('/api/projects/{pid}/records/{rid}/reviews')
    def reviews(pid:str,rid:str):
        with store.db() as db:
            store.get(db,pid,rid)
            return [dict(r) for r in db.execute('SELECT * FROM reviews WHERE record_id=? ORDER BY created DESC',(rid,))]

    @app.post('/api/projects/{pid}/records/{rid}/reviews')
    def review(pid:str,rid:str,body:ReviewIn):
        with store.db() as db:
            r=store.get(db,pid,rid,body.version)
            value={'id':uid(),'record_id':rid,'version':body.version,'decision':body.decision,'note':body.note,'source':r['source'],'created':now()}
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',tuple(value.values()))
            return value

    @app.post('/api/projects/{pid}/records/{rid}/adopt')
    def adopt(pid:str,rid:str,body:AdoptIn):
        with store.db() as db:
            r=store.get(db,pid,rid,body.version)
            if r['kind'] not in ('image','asset','style'): raise HTTPException(422,'只有图片支持选择采用版本')
            db.execute('UPDATE records SET adopted=? WHERE id=?',(body.version,rid))
            return store.get(db,pid,rid)

    @app.post('/api/projects/{pid}/style-selection')
    def select_style(pid:str,body:SelectionIn):
        with store.db() as db:
            r=store.get(db,pid,body.record_id,body.version)
            if r['kind']!='style' or r['review']!='approved': raise HTTPException(422,'请先审核通过要采用的画风版本')
            db.execute("INSERT INTO selections VALUES(?,?,?,?) ON CONFLICT(project_id,kind) DO UPDATE SET record_id=excluded.record_id,version=excluded.version",(pid,'style',body.record_id,body.version))
            return {'record_id':body.record_id,'version':body.version,'source':r['source']}

    @app.get('/api/projects/{pid}/batch-reviews')
    def batch_reviews(pid:str,batch:int):
        with store.db() as db:
            store.project(db,pid)
            output=[]
            for row in db.execute('SELECT * FROM batch_reviews WHERE project_id=? AND batch=? ORDER BY created DESC',(pid,batch)):
                item=dict(row); item['records']=json.loads(item['records'])
                item['stale']=any(store.get(db,pid,ref['id'])['version']!=ref['version'] for ref in item['records'])
                output.append(item)
            return output

    @app.post('/api/projects/{pid}/batch-review')
    def batch_review(pid:str,body:BatchReviewIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshots=[]
            for ref in body.records:
                r=store.get(db,pid,ref.get('id'))
                if r['kind']!='script' or r['content'].get('batch')!=body.batch: raise HTTPException(422,'审核范围不属于当前批次脚本')
                if r['version']!=ref.get('version'): raise HTTPException(409,'批次脚本版本已变化，请重新查看后审核')
                snapshots.append(r)
            for r in snapshots:
                db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],r['version'],body.decision,body.note,r['source'],now()))
            db.execute('INSERT INTO batch_reviews VALUES(?,?,?,?,?,?,?)',(uid(),pid,body.batch,dump([{'id':r['id'],'version':r['version'],'source':r['source']} for r in snapshots]),body.decision,body.note,now()))
            return {'reviewed':len(snapshots),'batch':body.batch}

    @app.get('/api/projects/{pid}/gates')
    def gates(pid:str,batch:int=1):
        with store.db() as db:
            store.project(db,pid)
            rows=[store.get(db,pid,r['id']) for r in db.execute('SELECT id FROM records WHERE project_id=?',(pid,))]
            reasons=[]
            for kind,label in [('original','导入小说原著'),('skeleton','全书骨架审核'),('outline','全书细纲审核'),('style','画风审核'),('asset','全面资产审核'),('script','当前批次脚本审核'),('trial','首话试制确认')]:
                candidates=[r for r in rows if r['kind']==kind and r['source']!='mock' and not r['content'].get('pending_for') and (kind!='script' or r['content'].get('batch',1)==batch)]
                if kind=='style':
                    choice=db.execute("SELECT * FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
                    candidates=[r for r in candidates if choice and r['id']==choice['record_id'] and r['version']==choice['version']]
                if kind=='trial':
                    images=[r for r in rows if r['kind']=='image' and r['content'].get('episode')==1]
                    expected={(r['id'],r['adopted']) for r in images}
                    candidates=[r for r in candidates if expected and {(ref['id'],ref.get('version')) for ref in r['content'].get('references',[])}==expected and r['review']=='approved']
                if not candidates or any(r['source']=='mock' or (kind!='original' and r['review']!='approved') for r in candidates): reasons.append(label)
            selection=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
            return {'ready':not reasons,'reasons':reasons,'ai_connected':False,'selected_style':dict(selection) if selection else None}

    @app.post('/api/projects/{pid}/text')
    async def import_text(pid:str,file:UploadFile=File(...),encoding:str=Form('auto')):
        raw=await file.read(20*1024*1024+1)
        if len(raw)>20*1024*1024: raise HTTPException(413,'TXT 最大 20MB')
        if not (file.filename or '').lower().endswith('.txt'): raise HTTPException(422,'仅支持 TXT 文件')
        if encoding not in ('auto','utf-8-sig','gb18030'): raise HTTPException(422,'请选择 UTF-8 或 GB18030')
        text=None
        for codec in (['utf-8-sig','gb18030'] if encoding=='auto' else [encoding]):
            try:
                decoded=raw.decode(codec)
                if '\x00' in decoded or any(ord(x)<32 and x not in '\n\r\t' for x in decoded): continue
                text=decoded; encoding=codec; break
            except UnicodeError: pass
        if text is None: raise HTTPException(422,'无法可靠解码，请明确选择编码后重试')
        if not text.strip(): raise HTTPException(422,'文件没有正文')
        chapters=[{'title':m.group().strip(),'offset':m.start()} for m in re.finditer(r'(?m)^\s*第[零〇一二三四五六七八九十百千万两\d]+[章回节卷][^\n]*',text)]
        if chapters and chapters[0]['offset']>0 and text[:chapters[0]['offset']].strip(): chapters.insert(0,{'title':'前言','offset':0})
        with store.db() as db:
            store.project(db,pid)
            url=store.file(db,pid,file.filename,raw,'text/plain')
            return store.add(db,pid,'original',file.filename,{'text':text,'encoding':encoding,'chapters':chapters,'url':url,'size':len(raw)},'import')

    @app.get('/api/projects/{pid}/files/{fid}')
    def file_response(pid:str,fid:str,download:bool=False):
        with store.db() as db:
            row=db.execute('SELECT * FROM files WHERE id=? AND project_id=?',(fid,pid)).fetchone()
            if not row: raise HTTPException(404,'文件不存在')
            return FileResponse(store.root/'files'/row['id'],media_type=row['mime'],filename=row['name'] if download else None)

    @app.post('/api/projects/{pid}/images')
    async def import_image(pid:str,file:UploadFile=File(...),kind:str=Form('image'),record_id:str=Form(''),expected_version:int=Form(0),batch:int=Form(1),episode:int=Form(1),panel:int=Form(1),category:str=Form('人物')):
        if kind not in ('image','asset','style'): raise HTTPException(422,'图片类型无效')
        if min(batch,episode,panel)<1: raise HTTPException(422,'话格编号需为正整数')
        raw=await file.read(30*1024*1024+1)
        if len(raw)>30*1024*1024: raise HTTPException(413,'图片最大 30MB')
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('PNG','JPEG'): raise ValueError()
                width,height=im.size
                if width*height>40_000_000: raise ValueError()
                mime='image/png' if im.format=='PNG' else 'image/jpeg'
                im.verify()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError): raise HTTPException(422,'请导入有效的 PNG/JPEG（不超过四千万像素）')
        with store.db() as db:
            store.project(db,pid)
            old=store.get(db,pid,record_id) if record_id else None
            if old and (old['kind']!=kind or old['version']!=expected_version): raise HTTPException(409,'图片版本已变化，请刷新后重试')
            url=store.file(db,pid,file.filename or '图片.png',raw,mime)
            content={**(old['content'] if old else {}),'url':url,'width':width,'height':height,'filename':file.filename,'issues':[],'checked':False}
            if not old: content.update(batch=batch,episode=episode,panel=panel,category=category,characters='',scene='',state='默认状态')
            if old: return store.save(db,pid,record_id,expected_version,content,source='import')
            return store.add(db,pid,kind,file.filename or '图片',content,'import')

    def image_snapshot(db,pid,rid,version):
        r=store.get(db,pid,rid,version)
        if r['kind'] not in ('image','asset','style') or not r['content'].get('url'): raise HTTPException(422,'此版本没有底图')
        return r

    @app.get('/api/projects/{pid}/records/{rid}/annotations')
    def annotations(pid:str,rid:str,image_version:int):
        with store.db() as db:
            image_snapshot(db,pid,rid,image_version)
            row=db.execute('SELECT * FROM annotations WHERE record_id=? AND image_version=?',(rid,image_version)).fetchone()
            return {'version':row['version'],'items':json.loads(row['items'])} if row else {'version':0,'items':[]}

    @app.put('/api/projects/{pid}/records/{rid}/annotations')
    def save_annotations(pid:str,rid:str,body:AnnotationIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=image_snapshot(db,pid,rid,body.image_version)
            row=db.execute('SELECT version FROM annotations WHERE record_id=? AND image_version=?',(rid,body.image_version)).fetchone()
            version=row['version'] if row else 0
            if body.expected_version!=version: raise HTTPException(409,'标注已被更新，当前内容已保留')
            w,h=r['content']['width'],r['content']['height']
            import math
            for item in body.items:
                if item.get('type') not in ('point','rect','brush','protect') or not isinstance(item.get('id'),str): raise HTTPException(422,'标注格式错误')
                for key,limit in [('x',w),('y',h),('width',w),('height',h)]:
                    v=item.get(key,0)
                    if not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<=v<=limit: raise HTTPException(422,'标注超出原图范围')
                if item.get('x',0)+item.get('width',0)>w or item.get('y',0)+item.get('height',0)>h: raise HTTPException(422,'标注超出原图范围')
                if item.get('type')=='brush':
                    width=item.get('brushWidth',16)
                    if not isinstance(width,(float,int)) or not math.isfinite(width) or not 0<width<=max(w,h): raise HTTPException(422,'画笔宽度必须是有效原图单位')
                pts=item.get('points',[])
                if len(pts)%2 or len(pts)>20000 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=(w if i%2==0 else h) for i,v in enumerate(pts)): raise HTTPException(422,'画笔坐标错误')
            db.execute('INSERT INTO annotations VALUES(?,?,?,?) ON CONFLICT(record_id,image_version) DO UPDATE SET version=excluded.version,items=excluded.items',(rid,body.image_version,version+1,dump(body.items)))
            return {'version':version+1,'items':body.items}

    @app.post('/api/projects/{pid}/download')
    def download(pid:str,body:DownloadIn):
        output=io.BytesIO()
        with store.db() as db,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for rid in dict.fromkeys(body.ids):
                head=store.get(db,pid,rid)
                r=image_snapshot(db,pid,rid,head['adopted'])
                fid=r['content']['url'].split('/')[-1]
                row=db.execute('SELECT * FROM files WHERE id=? AND project_id=?',(fid,pid)).fetchone()
                if not row: raise HTTPException(404,'图片文件缺失')
                safe=re.sub(r'[^\w.\-\u4e00-\u9fff]','_',row['name'])
                archive.writestr(f'{rid[:8]}_v{r["version"]}_{safe}',(store.root/'files'/fid).read_bytes())
        return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="selected-images.zip"'})

    async def run_task(tid):
        with store.db() as db:
            row=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not row or row['status']!='queued': return
            payload=json.loads(row['payload']); pid=row['project_id']
            db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?",(now(),tid))
        await asyncio.sleep(0.35)
        try:
            if payload.get('fail'): raise ValueError('演示失败：本次模拟没有生成结果，可重试。')
            with store.db() as db:
                old=store.get(db,pid,payload['target_id'],payload.get('base_image_version') or payload['input_version']) if payload.get('target_id') else None
                current=store.get(db,pid,payload['target_id']) if old else None
                stale=old and payload['input_version']!=current['version']
                kind=payload['kind']
                content=old['content'].copy() if old else {'batch':payload['batch'],'episode':payload['episode'],'panel':payload['panel']}
                if kind in ('image','repair','style','asset'):
                    raw=demo_image(payload['panel']-1)
                    content.update(url=store.file(db,pid,'模拟样例.png',raw,'image/png'),width=640,height=900,filename='模拟样例.png',checked=True,issues=[{'id':uid(),'severity':'minor','text':'模拟复查记录：此图仅用于界面演示，不代表图像质量通过。','basis':'预置流程样例'}],category=content.get('category','人物'),state=content.get('state','示例状态'),characters=content.get('characters','阿青'),scene=content.get('scene','旧院'))
                    outkind=old['kind'] if old else ('image' if kind=='repair' else kind)
                else:
                    content=content_for(kind,content,payload); outkind=kind
                if old and not stale and old['kind']==outkind:
                    result=store.save(db,pid,old['id'],payload['input_version'],content,source='mock')
                else:
                    if stale: content['pending_for']=old['id']
                    result=store.add(db,pid,outkind,('待处理回复 · ' if stale else '')+{'memory':'人物关系示例','skeleton':'全书骨架','outline':'分集细纲','script':'逐格脚本','package':'逐格生图包','style':'画风样例','asset':'资产样例','image':'模拟图片','repair':'修改结果'}.get(kind,kind),content,'mock')
                db.execute('UPDATE tasks SET status=?,output_id=?,error=?,updated=? WHERE id=?',('pending' if stale else 'succeeded',result['id'],'输入已变化，结果另存为待处理版本' if stale else '',now(),tid))
        except Exception as exc:
            # Never include provider credentials or request payload in errors.
            message=str(exc) if isinstance(exc,(ValueError,HTTPException)) else '模拟任务未完成，请重试'
            with store.db() as db: db.execute("UPDATE tasks SET status='failed',error=?,updated=? WHERE id=?",(message,now(),tid))

    @app.get('/api/projects/{pid}/tasks')
    def tasks(pid:str):
        with store.db() as db:
            store.project(db,pid)
            return [{**dict(r),'payload':json.loads(r['payload']),'source':'mock'} for r in db.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created DESC',(pid,))]

    @app.post('/api/projects/{pid}/tasks')
    def start_task(pid:str,body:TaskIn,background:BackgroundTasks):
        with store.db() as db:
            store.project(db,pid)
            if body.target_id:
                r=store.get(db,pid,body.target_id)
                if body.input_version!=r['version']: raise HTTPException(409,'任务输入已变化，请重新发起')
                if r['kind']=='original': raise HTTPException(422,'任务不能覆盖原著')
            payload=body.model_dump()
            if body.kind=='repair':
                if not body.target_id: raise HTTPException(422,'修改需要指定底图')
                image=image_snapshot(db,pid,body.target_id,body.base_image_version or body.input_version)
                ann=db.execute('SELECT version,items FROM annotations WHERE record_id=? AND image_version=?',(body.target_id,image['version'])).fetchone()
                payload.update(base_image_version=image['version'],base_image_url=image['content']['url'],annotation_snapshot={'version':ann['version'] if ann else 0,'items':json.loads(ann['items']) if ann else []})
            tid,stamp=uid(),now()
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(tid,pid,'queued',dump(payload),None,'',stamp,stamp))
        background.add_task(run_task,tid)
        return {'id':tid,'status':'queued','source':'mock'}

    @app.post('/api/projects/{pid}/tasks/{tid}/retry')
    def retry(pid:str,tid:str,background:BackgroundTasks):
        with store.db() as db:
            row=db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            if not row: raise HTTPException(404,'任务不存在')
            if row['status'] not in ('failed','interrupted'): raise HTTPException(409,'仅失败或中断任务可重试')
            payload=json.loads(row['payload']); payload['fail']=False
            if payload.get('target_id') and store.get(db,pid,payload['target_id'])['version']!=payload['input_version']: raise HTTPException(409,'原输入版本已变化，请发起新任务')
            db.execute("UPDATE tasks SET status='queued',payload=?,error='',updated=? WHERE id=?",(dump(payload),now(),tid))
        background.add_task(run_task,tid)
        return {'id':tid,'status':'queued'}

    def settings_profiles(db):
        row=db.execute('SELECT content FROM settings WHERE id=1').fetchone()
        data=json.loads(row['content']) if row else {}
        return {data.get('purpose','text'):data} if 'purpose' in data else data

    def settings_value(db,purpose='text'):
        value=settings_profiles(db).get(purpose,{'url':'','model':'','purpose':purpose}).copy()
        value.update(connection='unverified',has_secret=False,vault_error=None)
        try: value['has_secret']=bool(vault.get_password('comic-workbench','provider:'+purpose))
        except Exception: value['vault_error']='无法访问 macOS 钥匙串；密钥未读取，不使用明文替代'
        return value

    @app.get('/api/settings')
    def settings(purpose:Literal['text','image','vision']='text'):
        with store.db() as db: return settings_value(db,purpose)

    @app.put('/api/settings')
    def save_settings(body:SettingsIn):
        if body.url and urlparse(body.url).scheme not in ('http','https'): raise HTTPException(422,'服务地址必须使用 http 或 https')
        if body.secret:
            try: vault.set_password('comic-workbench','provider:'+body.purpose,body.secret)
            except Exception: raise HTTPException(503,'密钥无法保存到 macOS 钥匙串；未写入明文，请检查钥匙串授权')
        with store.db() as db:
            profiles=settings_profiles(db)
            profiles[body.purpose]=body.model_dump(exclude={'secret'})
            db.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content',(dump(profiles),))
            return settings_value(db,body.purpose)

    frontend=Path(__file__).resolve().parents[1]/'frontend'/'dist'
    if frontend.exists(): app.mount('/',StaticFiles(directory=frontend,html=True),name='frontend')
    return app
