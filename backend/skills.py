"""Immutable, data-only skill bundles. Import never executes uploaded code."""
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Literal
from fastapi import HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,model_validator,model_serializer,PrivateAttr
from .store import dump,now
from .skill_references import safe_path,links,cross_reference,local_reference,ID,VERSION

Stage=Literal['setup','memory','skeleton','outline','style','asset','script','package','image','review']

class SkillDependency(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern='^'+ID+'$')
    version:str=Field(pattern='^'+VERSION+'$')

class SkillPackage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['comic-skill/v1']
    id:str=Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$')
    name:str=Field(min_length=1,max_length=120)
    version:str=Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9._-]+$')
    stages:list[Stage]=Field(min_length=1,max_length=10)
    tags:list[str]=Field(default_factory=list,max_length=20)
    entrypoint:str='SKILL.md'
    files:dict[str,str]
    dependencies:list[SkillDependency]=Field(default_factory=list,max_length=20)
    _cross_references:list[dict]=PrivateAttr(default_factory=list)

    @model_serializer(mode='wrap')
    def serialize(self,handler):
        value=handler(self)
        if not value.get('dependencies'):value.pop('dependencies',None)
        return value

    @model_validator(mode='after')
    def validate_files(self):
        if not self.files or len(self.files)>1500 or self.entrypoint not in self.files:raise ValueError('missing_entry')
        total=0
        for path,text in self.files.items():
            safe_path(path)
            if PurePosixPath(path).suffix.lower() not in ('.md','.txt','.json','.py','.js','.mjs','.csv','.yaml','.yml'):raise ValueError('unsupported_resource')
            if '\x00' in text or len(text)>500000:raise ValueError('invalid_text')
            # Obvious credentials belong in the separate keychain configuration flow.
            if re.search(r'\bsk-[A-Za-z0-9_-]{16,}',text):raise ValueError('credential_in_resource')
            total+=len(text.encode())
        required={(d.id,d.version) for d in self.dependencies};cross_edges={}
        if len({d.id for d in self.dependencies})!=len(self.dependencies) or any(d.id==self.id for d in self.dependencies):raise ValueError('invalid_dependencies')
        for path,text in self.files.items():
            if path.lower().endswith('.md'):
                for target in links(text):
                    cross=cross_reference(target)
                    if cross:
                        if (cross['id'],cross['version']) not in required:raise ValueError('undeclared_dependency')
                        cross_edges[(path,cross['id'],cross['version'],cross['path'])]={'source':path,**cross}
                        if len(cross_edges)>1500:raise ValueError('cross_reference_limit')
                    else:
                        resolved=local_reference(path,target)
                        if resolved and resolved not in self.files:raise ValueError('missing_reference')
        self._cross_references=list(cross_edges.values())
        if total>8*1024*1024 or len(self.files[self.entrypoint])>30000:raise ValueError('bundle_too_large')
        if any(len(tag)>80 for tag in self.tags):raise ValueError('invalid_tags')
        self.stages=list(dict.fromkeys(self.stages));self.tags=list(dict.fromkeys(self.tags))
        return self


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS skill_packages(hash TEXT PRIMARY KEY,skill_id TEXT,version TEXT,name TEXT,manifest TEXT,created TEXT,UNIQUE(skill_id,version));
    CREATE TABLE IF NOT EXISTS skill_files(hash TEXT,path TEXT,content TEXT,PRIMARY KEY(hash,path));
    CREATE TABLE IF NOT EXISTS project_skill_settings(project_id TEXT PRIMARY KEY,revision INTEGER,hashes TEXT);
    ''')


def package_info(db,digest):
    row=db.execute('SELECT * FROM skill_packages WHERE hash=?',(digest,)).fetchone()
    if not row:raise HTTPException(404,'Skill版本不存在')
    return {'hash':digest,**json.loads(row['manifest']),'created':row['created']}


def project_selection(store,db,pid):
    store.project(db,pid)
    row=db.execute('SELECT * FROM project_skill_settings WHERE project_id=?',(pid,)).fetchone()
    return {'revision':row['revision'] if row else 0,'hashes':json.loads(row['hashes']) if row else []}


def validate_selection(db,hashes):
    if len(hashes)>20 or len(set(hashes))!=len(hashes):raise HTTPException(422,'流程选择最多20个固定版本且不能重复')
    choices=[package_info(db,digest) for digest in hashes]
    if len({info['id'] for info in choices})!=len(choices):raise HTTPException(422,'同一流程只能启用一个版本')
    selected={info['id']:info for info in choices}
    for info in choices:
        for dep in info.get('dependencies',[]):
            actual=selected.get(dep['id'])
            if not actual or actual['version']!=dep['version']:raise HTTPException(422,'请在本项目同时启用依赖 '+dep['id']+' v'+dep['version']+'；未更新选择')
        for ref in info.get('cross_references',[]):
            actual=selected.get(ref['id'])
            if not actual or actual['version']!=ref['version'] or ref['path'] not in actual['files']:raise HTTPException(422,'Skill跨包引用缺少所选固定版本的资料；未更新选择')
    return choices


def frozen_skills(store,db,pid,stage=None):
    selection=project_selection(store,db,pid)
    choices=validate_selection(db,selection['hashes']);by_id={info['id']:info for info in choices}
    roots=[info for info in choices if stage is None or stage in info['stages']]
    root_ids={info['id'] for info in roots};pending=list(roots);frozen={}
    while pending:
        info=pending.pop(0)
        if info['id'] in frozen:continue
        frozen[info['id']]={**info,**({'resource_only':True} if info['id'] not in root_ids else {})}
        pending.extend(by_id[dep['id']] for dep in info.get('dependencies',[]))
    return list(frozen.values())


def resolve_cross_reference(selected,source,target):
    try:ref=cross_reference(target)
    except ValueError:raise HTTPException(422,'跨包引用格式无效，不读取网络或外部目录')
    if not ref:return None
    if not any(d['id']==ref['id'] and d['version']==ref['version'] for d in source.get('dependencies',[])):raise HTTPException(403,'跨包引用不在来源Skill声明的依赖中')
    actual=next((info for info in selected if info['id']==ref['id'] and info['version']==ref['version']),None)
    if not actual or ref['path'] not in actual['files']:raise HTTPException(403,'引用资料不在本次冻结依赖范围中')
    return actual,ref['path']


def stage_instructions(db,selected):
    pieces=[]
    for info in selected:
        if info.get('resource_only'):continue
        text=db.execute('SELECT content FROM skill_files WHERE hash=? AND path=?',(info['hash'],info['entrypoint'])).fetchone()['content']
        pieces.append(f"流程 {info['name']} v{info['version']}（hash={info['hash']}，入口={info['entrypoint']}）\n{text}")
    dependencies=[info for info in selected if info.get('resource_only')]
    if dependencies:pieces.append('本次跨包只读资料绑定（不自动启用其主流程；可用来源hash和skill://id@version/path读取）：\n'+'\n'.join(f"{i['id']}@{i['version']} → hash={i['hash']}" for i in dependencies))
    result='\n\n'.join(pieces)
    if len(result)>80000:raise HTTPException(422,'本阶段启用的主规则过多，请减少项目流程选择；资料仍可按需读取')
    return result


def freeze_stage_resources(store,db,pid,stage):
    selected=frozen_skills(store,db,pid,stage);by_hash={info['hash']:info for info in selected}
    pending=[(info['hash'],info['entrypoint']) for info in selected if not info.get('resource_only')]
    visited=set();groups={};total=0
    while pending:
        digest,path=pending.pop(0)
        if (digest,path) in visited:continue
        visited.add((digest,path));info=by_hash[digest]
        if path not in info['files']:raise HTTPException(422,'Skill引用资源缺失，未提交模型请求')
        row=db.execute('SELECT content FROM skill_files WHERE hash=? AND path=?',(digest,path)).fetchone()
        if not row:raise HTTPException(422,'Skill引用资源缺失，未提交模型请求')
        text=row['content'];total+=len(text)
        if total>80000 or len(visited)>1500:raise HTTPException(422,'Skill必需规则及引用资源过多，请减少启用流程；未截断规则')
        if digest not in groups:groups[digest]={**{k:info[k] for k in ('hash','id','name','version','entrypoint')},**({'resource_only':True} if info.get('resource_only') else {}),'resources':[]}
        groups[digest]['resources'].append({'path':path,'text':text})
        if path.lower().endswith('.md'):
            for target in links(text):
                crossed=resolve_cross_reference(selected,info,target)
                if crossed:pending.append((crossed[0]['hash'],crossed[1]))
                else:
                    local=local_reference(path,target)
                    if local:pending.append((digest,local))
    return list(groups.values())


def read_resource(db,digest,path,start=0):
    row=db.execute('SELECT content FROM skill_files WHERE hash=? AND path=?',(digest,path)).fetchone()
    if not row:raise HTTPException(404,'Skill资料不存在')
    text=row['content']
    return {'hash':digest,'path':path,'start':start,'end':min(len(text),start+10000),'total_chars':len(text),'text':text[start:start+10000]}


def install(store,value):
    try:pack=SkillPackage.model_validate(value)
    except Exception:raise HTTPException(422,'Skill包格式或资料无效，请检查manifest、入口、路径、文本大小和凭据；未安装或执行文件')
    content=pack.model_dump();digest=hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    metadata={k:v for k,v in content.items() if k!='files'}
    metadata['files']=list(sorted(pack.files))
    if pack.dependencies:
        metadata['cross_references']=pack._cross_references

    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT hash FROM skill_packages WHERE skill_id=? AND version=?',(pack.id,pack.version)).fetchone()
        if old:
            if old['hash']!=digest:raise HTTPException(409,'相同Skill标识和版本已有不同内容，请提高版本号后导入')
            return package_info(db,digest)
        db.execute('INSERT INTO skill_packages VALUES(?,?,?,?,?,?)',(digest,pack.id,pack.version,pack.name,dump(metadata),now()))
        db.executemany('INSERT INTO skill_files VALUES(?,?,?)',[(digest,path,text) for path,text in pack.files.items()])
        return package_info(db,digest)


def parse_bundle(raw):
    if not raw.startswith(b'PK'):return json.loads(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist()
        if len(infos)>1600 or sum(i.file_size for i in infos)>8*1024*1024:raise ValueError('archive_limit')
        files={}
        for info in infos:
            if info.is_dir():continue
            safe_path(info.filename)
            if stat.S_ISLNK(info.external_attr>>16) or info.flag_bits&1 or info.filename in files:raise ValueError('unsafe_zip')
            files[info.filename]=archive.read(info).decode('utf-8-sig')
        manifest=json.loads(files.pop('manifest.json'))
        if 'files' in manifest:raise ValueError('duplicate_manifest_files')
        return {**manifest,'files':files}


class SelectionIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    hashes:list[str]=Field(max_length=20)


def register_skills(app,store):
    with store.db() as db:schema(db)

    @app.get('/api/skills')
    def catalog():
        with store.db() as db:return [package_info(db,r['hash']) for r in db.execute('SELECT hash FROM skill_packages ORDER BY created DESC')]

    @app.post('/api/skills/import')
    async def import_skill(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>10*1024*1024:raise HTTPException(413,'Skill包最多10MB')
            raw.extend(chunk)
        try:value=parse_bundle(bytes(raw))
        except Exception:raise HTTPException(422,'Skill包无法读取，请提供comic-skill/v1 JSON或含manifest.json的ZIP')
        return install(store,value)

    @app.get('/api/skills/{digest}/resource')
    def resource(digest:str,path:str='SKILL.md',start:int=0):
        if start<0:raise HTTPException(422,'起点无效')
        with store.db() as db:
            package_info(db,digest)
            return read_resource(db,digest,path,start)

    @app.get('/api/projects/{pid}/skills')
    def get_selection(pid:str):
        with store.db() as db:return project_selection(store,db,pid)

    @app.put('/api/projects/{pid}/skills')
    def select(pid:str,body:SelectionIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');current=project_selection(store,db,pid)
            if current['revision']!=body.expected_revision:raise HTTPException(409,'项目流程选择已变化，请刷新后重选')
            if len(set(body.hashes))!=len(body.hashes):raise HTTPException(422,'不能重复选择同一Skill版本')
            validate_selection(db,body.hashes)
            revision=current['revision']+1
            db.execute('INSERT INTO project_skill_settings VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,hashes=excluded.hashes',(pid,revision,dump(body.hashes)))
            return {'revision':revision,'hashes':body.hashes}
