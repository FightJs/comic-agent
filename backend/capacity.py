"""Shared, adjustable task capacity. Credentials and provider profiles stay elsewhere."""
import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .store import dump

DEFAULTS={'text':2,'image':1,'vision':1}

class CapacityCancelled(RuntimeError):pass
class CapacityClosed(RuntimeError):pass

@dataclass(eq=False)
class Lease:
    pool:object
    task:object
    key:str|None
    active:bool=False
    cancelled:bool=False


class CapacityPool:
    def __init__(self,limit):
        self.limit=limit;self.active=0;self.queue=deque();self.loop=None;self.condition=asyncio.Condition();self.closed=False;self.waker=None;self.anonymous=deque();self.contexts={}

    def bind(self):
        loop=asyncio.get_running_loop()
        if self.loop is not loop:
            if self.active or self.queue:raise RuntimeError('capacity_cross_loop')
            self.loop=loop;self.condition=asyncio.Condition()
        return loop

    def snapshot(self):return {'limit':self.limit,'active':self.active,'waiting':sum(not t.cancelled for t in self.queue)}
    def locked(self):return self.active>=self.limit

    async def notify(self):
        async with self.condition:self.condition.notify_all()

    def wake(self):
        if not self.waker or self.waker.done():self.waker=self.loop.create_task(self.notify())

    async def enter(self,key=None):
        self.bind();ticket=Lease(self,asyncio.current_task(),key)
        async with self.condition:
            self.queue.append(ticket)
            try:
                await self.condition.wait_for(lambda:self.closed or ticket.cancelled or (self.queue[0] is ticket and self.active<self.limit))
                if self.closed:raise CapacityClosed('运行容量已关闭，未派发')
                if ticket.cancelled:raise CapacityCancelled('等待容量时已停止，未派发')
                self.queue.popleft();self.active+=1;ticket.active=True;self.condition.notify_all()
                return ticket
            except BaseException:
                if ticket in self.queue:self.queue.remove(ticket)
                self.condition.notify_all();raise

    def leave(self,ticket):
        if not ticket.active:return
        ticket.active=False;self.active-=1;self.wake()

    @asynccontextmanager
    async def hold(self,key=None):
        ticket=await self.enter(key)
        try:yield ticket
        finally:self.leave(ticket)

    async def acquire(self):
        self.anonymous.append(await self.enter());return True

    def release(self):
        def finish():
            if not self.anonymous:raise RuntimeError('capacity_release_without_acquire')
            self.leave(self.anonymous.popleft())
        if self.loop is None or self.loop.is_closed():raise RuntimeError('capacity_loop_unavailable')
        try:current=asyncio.get_running_loop()
        except RuntimeError:current=None
        if current is self.loop:finish()
        else:self.loop.call_soon_threadsafe(finish)

    async def __aenter__(self):
        ticket=await self.enter();self.contexts.setdefault(asyncio.current_task(),[]).append(ticket);return ticket

    async def __aexit__(self,*args):
        stack=self.contexts[asyncio.current_task()];self.leave(stack.pop())
        if not stack:self.contexts.pop(asyncio.current_task(),None)

    def cancel(self,key):
        def mark():
            for ticket in self.queue:
                if ticket.key==key:ticket.cancelled=True
            self.wake()
        if self.loop and not self.loop.is_closed():self.loop.call_soon_threadsafe(mark)

    async def resize(self,limit):
        self.bind()
        async with self.condition:self.limit=limit;self.condition.notify_all()

    async def close(self):
        self.bind()
        async with self.condition:self.closed=True;self.condition.notify_all()

    def owns(self,lease):return isinstance(lease,Lease) and lease.pool is self and lease.active and lease.task is asyncio.current_task()


class Limits(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:int=Field(ge=1,le=8)
    image:int=Field(ge=1,le=8)
    vision:int=Field(ge=1,le=8)
class UpdateLimits(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expected_revision:int=Field(ge=0)
    limits:Limits


class CapacityManager:
    def __init__(self,store=None):
        self.store=store;self.update_lock=asyncio.Lock();limits=dict(DEFAULTS);self.revision=0
        if store:
            with store.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS runtime_limits(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER,content TEXT)')
                db.execute('INSERT OR IGNORE INTO runtime_limits VALUES(1,0,?)',(dump(limits),))
                row=db.execute('SELECT * FROM runtime_limits WHERE id=1').fetchone();limits=json.loads(row['content']);self.revision=row['revision']
        self.pools={role:CapacityPool(limits[role]) for role in DEFAULTS}

    def snapshot(self):return {'revision':self.revision,'limits':{k:p.limit for k,p in self.pools.items()},'usage':{k:p.snapshot() for k,p in self.pools.items()}}

    async def update(self,body):
        async with self.update_lock:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT revision FROM runtime_limits WHERE id=1').fetchone()
                if row['revision']!=body.expected_revision:raise HTTPException(409,'运行容量已被更新；当前草稿保留，请读取最新版本后核对')
                revision=row['revision']+1;values=body.limits.model_dump()
                db.execute('UPDATE runtime_limits SET revision=?,content=? WHERE id=1',(revision,dump(values)))
            for role,limit in values.items():await self.pools[role].resize(limit)
            self.revision=revision
        return self.snapshot()

    async def close(self):
        for pool in self.pools.values():await pool.close()


def register_capacity_api(app,manager):
    @app.get('/api/runtime/limits')
    async def read():return manager.snapshot()
    @app.put('/api/runtime/limits')
    async def update(body:UpdateLimits):return await manager.update(body)


def text_dispatch_guard(app,store,config,before=None,on_secret=None):
    """Revalidate frozen provider and business state after queueing; refresh only credentials."""
    from .config_packages import profiles
    def public(value):return (value.get('url','').rstrip('/'),value.get('model'),value.get('api') or 'openai-completions')
    def guard():
        with app.state.config_lock:
            with store.db() as db:
                if before:before(db)
                if public(profiles(db).get('text',{}))!=public(config):raise HTTPException(409,'等待容量期间文本配置已变化，未提交；请核对后重新发起')
            try:secret=app.state.provider_secret_get('text')
            except Exception:raise HTTPException(503,'无法读取文本钥匙串；未提交模型')
            if not isinstance(secret,str) or not secret:raise HTTPException(409,'文本密钥缺失，未提交模型')
            if on_secret:on_secret(secret)
            return {'secret':secret}
    return guard
