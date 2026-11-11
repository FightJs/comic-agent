"""Frozen UTF-16 text ranges; the editor supplies user-confirmed rich text."""
from html.parser import HTMLParser
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from .store import dump, is_primary

class SelectionIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    start:int=Field(ge=0,le=300000)
    end:int=Field(ge=1,le=300000)
    text:str=Field(min_length=1,max_length=20000)

class ApplyIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expected_version:int=Field(ge=1)
    html:str=Field(min_length=1,max_length=500000)

class FlatText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)

def plain(content):
    if isinstance(content.get('html'),str):
        parser=FlatText();parser.feed(content['html']);return ''.join(parser.parts)
    return content.get('text','').replace('\n','') if isinstance(content.get('text'),str) else ''

def split(text,selection):
    try:
        data=text.encode('utf-16-le')
        start,end=selection['start']*2,selection['end']*2
        if start>=end or end>len(data):raise ValueError()
        parts=[part.decode('utf-16-le') for part in (data[:start],data[start:end],data[end:])]
        if parts[1]!=selection['text']:raise ValueError()
        return parts
    except (ValueError,UnicodeError):raise HTTPException(422,'选段位置或原文不符，请重新选择已保存正文')

def validate(record,selection):
    if record['kind'] not in ('skeleton','outline'):raise HTTPException(422,'精确选段仅用于骨架或细纲正文')
    split(plain(record['content']),selection)

def register(app,store):
    @app.post('/api/projects/{pid}/agent/proposals/{proposal_id}/apply-selection')
    def apply(pid:str,proposal_id:str,body:ApplyIn):
        from .agent_changes import get
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            proposal=get(store,db,pid,proposal_id)
            changes=proposal['changes']
            if len(changes)!=1 or not changes[0].get('selection'):raise HTTPException(409,'此候选不是精确选段修改')
            change=changes[0]
            if proposal['status']=='adopted':
                ref=proposal['result']['records'][0]
                return store.get(db,pid,ref['id'],ref['version'])
            if proposal['status']!='pending':raise HTTPException(409,'此候选已拒绝')
            run=db.execute('SELECT status FROM agent_runs WHERE id=?',(proposal['run_id'],)).fetchone()
            if not run or run['status']!='completed':raise HTTPException(409,'请等待本次回复完整完成后采用')
            old=store.get(db,pid,change['id'])
            if old['version']!=change['version'] or body.expected_version!=change['version']:raise HTTPException(409,'原稿已有新版本，选段候选仍保留；请重新选择正文讨论')
            before,_,after=split(plain(old['content']),change['selection'])
            if plain({'html':body.html})!=before+change['patch']['text']+after:raise HTTPException(409,'提交正文不符合固定选段替换；选区外文字不能变化，候选仍保留')
            content={**old['content'],'html':body.html,'ai_run_id':proposal['run_id']}
            content.pop('text',None)
            saved=store.save(db,pid,old['id'],old['version'],content,source=proposal['source'])
            if is_primary(old):db.execute('UPDATE records SET adopted=? WHERE id=?',(saved['version'],saved['id']))
            db.execute("UPDATE agent_proposals SET status='adopted',result=? WHERE id=?",(dump({'records':[{'id':saved['id'],'version':saved['version']}],'graph':None}),proposal_id))
            return store.get(db,pid,saved['id'],saved['version'])
