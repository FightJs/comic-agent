"""Immutable retry grants and physical-attempt evidence; never dispatches network.

Host must bind only a newly authorized prepared call (never migrate a legacy failed
call), and run claim in the SAME BEGIN IMMEDIATE transaction as its current input,
config, cancellation, pause and budget guards. Only claimed=True permits one POST.
A crash with an unfinished attempt blocks retries; reopening never resumes work.
"""
import json
import re

from fastapi import HTTPException

from .store import dump, now, uid


def freeze_policy(value=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-{'version','max_not_sent_retries'}:raise HTTPException(422,'技术重试策略字段无效')
    version=value.get('version',1);retries=value.get('max_not_sent_retries',0)
    if type(version) is not int or version!=1 or type(retries) is not int or not 0<=retries<=4:raise HTTPException(422,'技术重试须明确为0至4次整数，策略版本为1')
    return {'version':1,'max_not_sent_retries':retries}


def network_limit(image_calls,policy=None):
    if type(image_calls) is not int or image_calls<0:raise HTTPException(422,'图像调用上限须为非负整数')
    return image_calls*(1+freeze_policy(policy)['max_not_sent_retries'])


def _hash(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise HTTPException(422,'输入和授权须绑定SHA256摘要')
    return value


def _transaction(db):
    if not db.in_transaction:raise HTTPException(409,'须在宿主授权守卫事务内登记图像尝试')


def _evidence(value):
    required={'outcome','response_started','transport_phase'}
    allowed=required|{'error_class','http_status','receipt_sha256'}
    if not isinstance(value,dict) or not required<=set(value) or set(value)-allowed:raise HTTPException(422,'尝试证据仅接受固定安全字段')
    if value['outcome'] not in ('not_sent','unknown','rejected','received','completed') or type(value['response_started']) is not bool:raise HTTPException(422,'尝试结果或响应证据无效')
    if value['transport_phase'] not in ('pool_acquire','connect','response_headers','response_body','unknown'):raise HTTPException(422,'传输阶段证据无效')
    if 'error_class' in value and value['error_class'] not in ('ConnectError','ConnectTimeout','PoolTimeout','ReadTimeout','WriteTimeout','ReadError','WriteError','RemoteProtocolError','CancelledError','unknown'):raise HTTPException(422,'异常类别须为固定安全枚举')
    if 'http_status' in value and (type(value['http_status']) is not int or not 100<=value['http_status']<=599):raise HTTPException(422,'HTTP状态证据无效')
    if 'receipt_sha256' in value:_hash(value['receipt_sha256'])
    phase=value['transport_phase'];started=value['response_started']
    if (phase in ('response_headers','response_body') or 'http_status' in value or 'receipt_sha256' in value) and not started:raise HTTPException(422,'已收到响应的证据不能声明未响应')
    if value['outcome'] in ('rejected','received','completed') and not started:raise HTTPException(422,'供应商终态须有响应证据')
    if value['outcome']=='not_sent':
        reliable=(phase=='pool_acquire' and value.get('error_class')=='PoolTimeout') or (phase=='connect' and value.get('error_class') in ('ConnectError','ConnectTimeout'))
        if started or not reliable or 'http_status' in value or 'receipt_sha256' in value:raise HTTPException(422,'尚不能证明请求未发送，不可登记为可重试')
    return dict(value)


class ImageAttempts:
    def __init__(self,store):
        self.store=store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS image_attempt_grants(
                    call_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,input_hash TEXT NOT NULL,
                    authorization_hash TEXT NOT NULL,policy TEXT NOT NULL,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS image_attempts(
                    id TEXT PRIMARY KEY,call_id TEXT NOT NULL,project_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,input_hash TEXT NOT NULL,authorization_hash TEXT NOT NULL,
                    previous_attempt_id TEXT,created TEXT NOT NULL,UNIQUE(call_id,sequence));
                CREATE TABLE IF NOT EXISTS image_attempt_results(
                    attempt_id TEXT PRIMARY KEY,evidence TEXT NOT NULL,created TEXT NOT NULL);
            ''')
            for table in ('image_attempt_grants','image_attempts','image_attempt_results'):
                for operation in ('UPDATE','DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable image attempt evidence'); END")
                key={'image_attempt_grants':'call_id','image_attempts':'id','image_attempt_results':'attempt_id'}[table]
                # SQLite REPLACE may bypass delete triggers when recursive triggers are off.
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key}) BEGIN SELECT RAISE(ABORT,'immutable image attempt evidence'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS image_attempts_no_sequence_replace BEFORE INSERT ON image_attempts WHEN EXISTS(SELECT 1 FROM image_attempts WHERE call_id=NEW.call_id AND sequence=NEW.sequence) BEGIN SELECT RAISE(ABORT,'immutable image attempt evidence'); END")

    def _grant(self,db,pid,cid):
        self.store.project(db,pid)
        row=db.execute('SELECT * FROM image_attempt_grants WHERE call_id=? AND project_id=?',(cid,pid)).fetchone()
        if not row:raise HTTPException(409,'没有此项目的冻结图像尝试授权；旧失败调用不能补造重试证据')
        return dict(row)

    def bind(self,db,pid,cid,input_hash,authorization_hash,policy=None):
        _transaction(db);self.store.project(db,pid)
        _hash(input_hash);_hash(authorization_hash);policy=freeze_policy(policy)
        if not isinstance(cid,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',cid):raise HTTPException(422,'逻辑调用编号无效')
        old=db.execute('SELECT * FROM image_attempt_grants WHERE call_id=?',(cid,)).fetchone()
        values=(pid,input_hash,authorization_hash,policy)
        if old:
            if (old['project_id'],old['input_hash'],old['authorization_hash'],json.loads(old['policy']))!=values:raise HTTPException(409,'不可更改冻结图像调用或重试授权')
        else:db.execute('INSERT INTO image_attempt_grants VALUES(?,?,?,?,?,?)',(cid,pid,input_hash,authorization_hash,dump(policy),now()))
        return self.list(db,pid,cid)

    def _attempt(self,db,row):
        value=dict(row)
        terminal=db.execute('SELECT evidence FROM image_attempt_results WHERE attempt_id=?',(row['id'],)).fetchone()
        value['evidence']=json.loads(terminal['evidence']) if terminal else None
        return value

    def list(self,db,pid,cid):
        grant=self._grant(db,pid,cid);policy=json.loads(grant['policy'])
        rows=db.execute('SELECT * FROM image_attempts WHERE call_id=? AND project_id=? ORDER BY sequence',(cid,pid)).fetchall()
        return {'call_id':cid,'policy':policy,'max_attempts':1+policy['max_not_sent_retries'],'remaining_attempts':max(0,1+policy['max_not_sent_retries']-len(rows)),'attempts':[self._attempt(db,r) for r in rows]}

    def claim(self,db,pid,cid,input_hash,authorization_hash,sequence):
        _transaction(db);_hash(input_hash);_hash(authorization_hash)
        grant=self._grant(db,pid,cid)
        if grant['input_hash']!=input_hash or grant['authorization_hash']!=authorization_hash:raise HTTPException(409,'图像尝试的输入或授权摘要不匹配')
        if type(sequence) is not int or sequence<1:raise HTTPException(422,'图像尝试序号须为正整数')
        history=self.list(db,pid,cid);attempts=history['attempts']
        if sequence<=len(attempts):return {**attempts[sequence-1],'claimed':False}
        if sequence!=len(attempts)+1 or sequence>history['max_attempts']:raise HTTPException(409,'图像尝试序号不连续或已达授权上限')
        previous=attempts[-1] if attempts else None
        if previous:
            evidence=previous['evidence']
            if not evidence or evidence.get('outcome')!='not_sent':raise HTTPException(409,'前次结果未明确证明未发送，不可重试')
            # Revalidate persisted evidence too; legacy/corrupt records grant no retry.
            try:_evidence(evidence)
            except HTTPException:raise HTTPException(409,'前次缺少可靠未发送证据，不可重试')
        aid=uid();stamp=now()
        db.execute('INSERT INTO image_attempts VALUES(?,?,?,?,?,?,?,?)',(aid,cid,pid,sequence,input_hash,authorization_hash,previous['id'] if previous else None,stamp))
        row=db.execute('SELECT * FROM image_attempts WHERE id=?',(aid,)).fetchone()
        return {**self._attempt(db,row),'claimed':True}

    def finish(self,db,pid,attempt_id,evidence):
        _transaction(db);self.store.project(db,pid);evidence=_evidence(evidence)
        row=db.execute('SELECT * FROM image_attempts WHERE id=? AND project_id=?',(attempt_id,pid)).fetchone()
        if not row:raise HTTPException(404,'图像尝试不属于本项目')
        old=db.execute('SELECT evidence FROM image_attempt_results WHERE attempt_id=?',(attempt_id,)).fetchone()
        if old:
            if json.loads(old['evidence'])!=evidence:raise HTTPException(409,'不可覆盖已保存的图像尝试终结证据')
        else:db.execute('INSERT INTO image_attempt_results VALUES(?,?,?)',(attempt_id,dump(evidence),now()))
        return self._attempt(db,row)
