#!/usr/bin/env python3
"""Offline synthetic stop/copy/restore drill. Never accepts a real data directory.

Only temporary synthetic files are written. No app startup, vault, provider, or
Pi run request is used. Node imports the existing ledger and locked Pi SDK only.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.store import Store


def inventory(root):
    """Relative file SHA256 manifest; reject links rather than escape the tree."""
    root=Path(root)
    if root.is_symlink():raise ValueError('backup_symlink')
    result={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('backup_symlink')
        if path.is_file():result[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_copy(expected,restored):
    if inventory(restored)!=expected:raise ValueError('backup_hash_mismatch')


NODE_DRILL=r'''
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {mkdirSync,writeFileSync} from 'node:fs';
import {RunCheckpoint} from './src/checkpoints.mjs';
import {SessionManager} from '@earendil-works/pi-coding-agent';
const root=process.env.BACKUP_VERIFY_ROOT;
const input={project_id:'synthetic_project',session_id:'synthetic_session',run_id:'paused_run',prompt:'synthetic fixed request',system:'synthetic rules',config:{url:'http://127.0.0.1:1/v1',model:'offline-fixture'},tools:true};
if(process.env.BACKUP_VERIFY_PHASE==='seed'){
 const dir=join(root,input.project_id,'sessions',input.session_id);mkdirSync(dir,{recursive:true,mode:0o700});
 const manager=SessionManager.create(root,dir);manager.appendMessage({role:'user',content:'synthetic conversation',timestamp:1});
 const ledger=RunCheckpoint.start(root,input);ledger.bindSession(manager);ledger.modelRequest();ledger.modelResponse({input:1,output:1,totalTokens:2});ledger.finish('paused','manual_pause');
 const unknown=RunCheckpoint.start(root,{...input,run_id:'unknown_run'});unknown.bindSession(manager);unknown.modelRequest();unknown.finish('paused','synthetic_unreturned_model');
 // Preserve opaque stale lock evidence. Copying it is never permission to replay.
 writeFileSync(join(root,input.project_id,'stale-lock.fixture'),'synthetic lock evidence',{mode:0o600});
 console.log(JSON.stringify({seeded:true}));
}else{
 const paused=RunCheckpoint.load(root,input),cp=paused.summary();assert.equal(cp.status,'paused');assert.equal(cp.unreturned_models,0);assert.equal(cp.session_saved,true);
 const planned=RunCheckpoint.continuation(root,{...input,run_id:'proposed_child',resume_from:input.run_id});
 const manager=SessionManager.open(planned.file);assert.ok(manager.getEntry(planned.leaf));assert.equal(manager.getLeafId(),planned.leaf);
 assert.throws(()=>RunCheckpoint.start(root,input),/run_recorded/);
 assert.throws(()=>RunCheckpoint.continuation(root,{...input,run_id:'forbidden_child',resume_from:'unknown_run'}),/checkpoint_unresolved/);
 assert.equal(RunCheckpoint.inspect(root,{...input,run_id:'unknown_run'}).unreturned_models,1);
 console.log(JSON.stringify({pi_session_branch_preserved:true,duplicate_run_rejected:true,unknown_model_continuation_rejected:true}));
}
'''


def _node(root,phase):
    env={key:os.environ[key] for key in ('PATH','SYSTEMROOT','TMPDIR') if key in os.environ}
    env.update(PI_OFFLINE='1',BACKUP_VERIFY_ROOT=str(root),BACKUP_VERIFY_PHASE=phase)
    result=subprocess.run(['node','--input-type=module','-e',NODE_DRILL],cwd=ROOT/'agent-runtime',env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('offline_pi_drill_failed (requires Node >=22.19 and installed agent-runtime dependencies)')
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_verification():
    with tempfile.TemporaryDirectory(prefix='comic-offline-restore-') as temporary:
        area=Path(temporary);source=area/'synthetic-data';store=Store(source)
        with store.db() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('synthetic_project','Synthetic backup drill',0,'t','t'))
            url=store.file(db,'synthetic_project','synthetic-original.txt',b'Synthetic original bytes\x00\xff','application/octet-stream')
            record=store.add(db,'synthetic_project','original','Synthetic original',{'url':url,'text':'Synthetic version one'},'import')
            store.save(db,'synthetic_project',record['id'],1,{**record['content'],'text':'Synthetic version two'})
        _node(source/'agent','seed')
        # All writers and DB connections have exited. Copy the entire tree,
        # including any WAL/SHM, checkpoints, sessions and opaque lock evidence.
        expected=inventory(source);backup=area/'backup';shutil.copytree(source,backup)
        verify_copy(expected,backup);restored=area/'isolated-restore';shutil.copytree(backup,restored);verify_copy(expected,restored)
        # Immutable mode is safe for this closed synthetic fixture only: the
        # final connection has checkpointed WAL. Do not use it on live databases.
        if (restored/'workbench.sqlite-wal').exists():raise ValueError('synthetic_wal_not_closed')
        with sqlite3.connect((restored/'workbench.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('sqlite_integrity_failed')
            versions=db.execute('SELECT version,content,source FROM versions ORDER BY version').fetchall()
            if len(versions)!=2 or [v[0] for v in versions]!=[1,2]:raise ValueError('versions_missing')
            if [json.loads(v[1])['text'] for v in versions]!=['Synthetic version one','Synthetic version two']:raise ValueError('version_content_mismatch')
            if not all(v[2]=='import' for v in versions):raise ValueError('version_source_mismatch')
            fid=db.execute('SELECT id FROM files').fetchone()[0]
            if (restored/'files'/fid).read_bytes()!=b'Synthetic original bytes\x00\xff':raise ValueError('original_bytes_mismatch')
        # Ledger inspection and duplicate/unresolved guards, no createAgentSession
        # or run/complete API. No child is claimed or dispatched.
        pi=_node(restored/'agent','inspect');verify_copy(expected,restored);verify_copy(expected,source)
        return {'sqlite_integrity':'ok','versions_preserved':len(versions),'original_hashes_match':True,**pi,'provider_calls':0,'real_data_accessed':False,'keychain_accessed':False,'temporary_data_cleaned':True}


if __name__=='__main__':
    if len(sys.argv)!=1:raise SystemExit('This synthetic-only drill accepts no data paths or options.')
    print(json.dumps(run_verification(),ensure_ascii=False,sort_keys=True))
