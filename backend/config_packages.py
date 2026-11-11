"""Configuration bootstrap: deterministic parsing; credentials never enter AI or disk."""
import hashlib
import json
import threading
import time
from typing import Literal
from urllib.parse import urlparse
from fastapi import Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .store import uid, dump


class ProviderProfile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    purpose:Literal['text','image','vision','parse']='text'
    url:str=Field(default='',max_length=2000)
    model:str=Field(default='',max_length=200)
    api:Literal['openai-completions','openai-responses','anthropic-messages','openai-images','mineru']|None=None
    secret:str|None=Field(default=None,max_length=10000)

    @model_validator(mode='after')
    def validate_profile(self):
        self.url=self.url.strip();self.model=self.model.strip()
        if self.url:
            parsed=urlparse(self.url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('invalid_url')
        allowed={'text':{'openai-completions','openai-responses','anthropic-messages'},'vision':{'openai-completions','openai-responses','anthropic-messages'},'image':{'openai-images'},'parse':{'mineru'}}
        if self.api and self.api not in allowed[self.purpose]:raise ValueError('invalid_protocol')
        return self


class ConfigPackage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['comic-config/v1']
    name:str=Field(min_length=1,max_length=120)
    profiles:list[ProviderProfile]=Field(min_length=1,max_length=4)

    @model_validator(mode='after')
    def complete(self):
        if len({p.purpose for p in self.profiles})!=len(self.profiles) or any(not p.url or not p.model for p in self.profiles):raise ValueError('invalid_profiles')
        public=[self.name]+[v for p in self.profiles for v in (p.url,p.model,p.api or '')]
        if any(p.secret and any(p.secret==v or (len(p.secret)>=6 and p.secret in v) for v in public) for p in self.profiles):raise ValueError('credential_in_metadata')
        return self


class ApplyPackage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=1,max_length=100)


def profiles(db):
    row=db.execute('SELECT content FROM settings WHERE id=1').fetchone()
    value=json.loads(row['content']) if row else {}
    return {value.get('purpose','text'):value} if 'purpose' in value else value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def write_profiles(store,vault,items,expected=None):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current=profiles(db)
        if expected is not None and fingerprint(current)!=expected:raise HTTPException(409,'配置在预览后发生变化，请重新导入并核对')
        changed=[];old={}
        try:
            for p in items:
                if p.secret:old[p.purpose]=vault.get_password('comic-workbench','provider:'+p.purpose)
            for p in items:
                if p.secret:
                    changed.append(p.purpose)
                    vault.set_password('comic-workbench','provider:'+p.purpose,p.secret)
                current[p.purpose]=p.model_dump(exclude={'secret'},exclude_none=True)
            db.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content',(dump(current),))
            db.commit()
        except Exception:
            rollback_failed=[]
            for purpose in reversed(changed):
                try:
                    if old[purpose] is not None:vault.set_password('comic-workbench','provider:'+purpose,old[purpose])
                    else:vault.delete_password('comic-workbench','provider:'+purpose)
                except Exception:rollback_failed.append(purpose)
            if rollback_failed:raise HTTPException(503,'配置未写入；部分钥匙串回滚失败，请在模型设置中重新核对用途：'+','.join(rollback_failed))
            raise HTTPException(503,'配置包应用失败，原配置已保留；请检查 macOS 钥匙串授权后重试')


def register_config_packages(app,store,vault_getter):
    staged={}
    lock=threading.RLock()
    app.state.config_lock=lock
    app.state.config_revision=0

    app.router.add_event_handler('shutdown',staged.clear)

    def prune():
        for token in list(staged):
            if staged[token]['expires']<time.monotonic():del staged[token]

    @app.post('/api/config-packages/preview')
    async def preview(request:Request):
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>1024*1024:raise HTTPException(413,'配置包最多1MB')
            raw.extend(chunk)
        try: package=ConfigPackage.model_validate(json.loads(raw))
        except Exception:raise HTTPException(422,'配置包格式无效：请使用 comic-config/v1，检查用途、地址、模型和字段；密钥未保存')
        with lock:
            prune()
            if len(staged)>=32:raise HTTPException(429,'待处理配置包过多，请稍后重试')
            with store.db() as db: expected=fingerprint(profiles(db))
            token=uid()
            staged[token]={'package':package,'expected':expected,'revision':app.state.config_revision,'expires':time.monotonic()+600,'result':None}
            return {'token':token,'name':package.name,'expires_in':600,'profiles':[{**p.model_dump(exclude={'secret'},exclude_none=True),'has_secret':bool(p.secret),'secret_action':'replace' if p.secret else 'preserve'} for p in package.profiles]}

    @app.post('/api/config-packages/discard')
    def discard(body:ApplyPackage):
        with lock:staged.pop(body.token,None)
        return {'discarded':True}

    @app.post('/api/config-packages/apply')
    def apply(body:ApplyPackage):
        with lock:
            prune();entry=staged.get(body.token)
            if not entry:raise HTTPException(410,'配置预览已过期或服务已重启，请重新选择文件')
            if entry['result']:return entry['result']
            if entry['revision']!=app.state.config_revision:raise HTTPException(409,'配置在预览后发生变化，请重新导入并核对')
            package=entry['package'];vault=vault_getter()
            write_profiles(store,vault,package.profiles,entry['expected'])
            app.state.config_revision+=1
            if hasattr(app.state,'graph_engine'):app.state.graph_engine.invalidate_config()
            result={'applied':[p.purpose for p in package.profiles],'connection':'unverified','name':package.name}
            entry['package']=None;entry['result']=result
            return result

    # Host-only hooks: the assistant receives public metadata, never the package secrets.
    def inspect_token(token):
        with lock:
            prune();entry=staged.get(token)
            if not entry:raise HTTPException(410,'配置预览已过期或服务已重启，请重新选择文件')
            if entry['result']:raise HTTPException(409,'配置包已应用，无需再次加入方案')
            package=entry['package']
            return {'name':package.name,'profiles':[{**p.model_dump(exclude={'secret'},exclude_none=True),'secret_action':'replace' if p.secret else 'preserve'} for p in package.profiles]}
    def package_secrets(token):
        with lock:
            prune();entry=staged.get(token)
            return [p.secret for p in entry['package'].profiles if p.secret] if entry and entry['package'] else []
    from types import SimpleNamespace
    app.state.config_packages=SimpleNamespace(inspect=inspect_token,secrets=package_secrets,apply=lambda token:apply(ApplyPackage(token=token)))
