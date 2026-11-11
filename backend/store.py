"""SQLite is the authority for versions; files are immutable and project scoped."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException


def uid(): return uuid.uuid4().hex

def now(): return datetime.now(timezone.utc).isoformat()

def dump(value): return json.dumps(value, ensure_ascii=False)

def is_primary(record):
    return record['adopted']>0 and not any(record['content'].get(k) for k in ('candidate_for','creation_candidate','pending_for','rejected','adopted_into','deleted_by_script'))


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'files').mkdir(exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,archived INTEGER DEFAULT 0,created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,kind TEXT,title TEXT,version INTEGER,adopted INTEGER,created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS versions(record_id TEXT,version INTEGER,content TEXT,source TEXT,created TEXT,PRIMARY KEY(record_id,version));
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,record_id TEXT,version INTEGER,decision TEXT,note TEXT,source TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS annotations(record_id TEXT,image_version INTEGER,version INTEGER,items TEXT,PRIMARY KEY(record_id,image_version));
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,mime TEXT);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT,status TEXT,payload TEXT,output_id TEXT,error TEXT,created TEXT,updated TEXT);
            CREATE INDEX IF NOT EXISTS records_project ON records(project_id,kind);
            CREATE INDEX IF NOT EXISTS reviews_version ON reviews(record_id,version);
            CREATE INDEX IF NOT EXISTS tasks_project ON tasks(project_id,created);
            CREATE TABLE IF NOT EXISTS batch_reviews(id TEXT PRIMARY KEY,project_id TEXT,batch INTEGER,records TEXT,decision TEXT,note TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS selections(project_id TEXT,kind TEXT,record_id TEXT,version INTEGER,PRIMARY KEY(project_id,kind));
            CREATE TABLE IF NOT EXISTS project_preferences(project_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),content TEXT);
            ''')
            db.execute("UPDATE tasks SET status='interrupted', error='应用重启，任务已中断；可手动重试' WHERE status IN ('queued','running')")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.root / 'workbench.sqlite', timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def project(self, db, pid):
        row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if not row: raise HTTPException(404, '项目不存在')
        return dict(row)

    def get(self, db, pid, rid, version=None):
        row = db.execute('SELECT * FROM records WHERE id=? AND project_id=?', (rid,pid)).fetchone()
        if not row: raise HTTPException(404, '内容不属于当前项目或已不存在')
        result = dict(row)
        v = version if version is not None else row['version']
        snapshot = db.execute('SELECT * FROM versions WHERE record_id=? AND version=?', (rid,v)).fetchone()
        if not snapshot: raise HTTPException(404, '版本不存在')
        result.update(content=json.loads(snapshot['content']), source=snapshot['source'], version=v)
        review = db.execute('SELECT decision FROM reviews WHERE record_id=? AND version=? ORDER BY created DESC LIMIT 1', (rid,v)).fetchone()
        result['review'] = review['decision'] if review else 'pending'
        return result

    def add(self, db, pid, kind, title, content, source='manual'):
        self.project(db,pid)
        rid, stamp = uid(), now()
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)', (rid,pid,kind,title,1,1,stamp,stamp))
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (rid,1,dump(content),source,stamp))
        db.execute('UPDATE projects SET updated=? WHERE id=?',(stamp,pid))
        return self.get(db,pid,rid)

    def save(self, db, pid, rid, expected, content, title=None, source='manual'):
        old = self.get(db,pid,rid)
        if old['content'].get('deleted_by_script'): raise HTTPException(409,'此内容已随脚本删除撤下；历史只读，请新建话格')
        if old['version'] != expected: raise HTTPException(409, '版本已更新。当前编辑已保留，请比较后重新保存。')
        keep_import=old['source']=='import' and (old['kind'] not in ('image','asset','style') or old['content'].get('url')==content.get('url'))
        source = 'mock' if 'mock' in (old['source'],source) else 'import' if keep_import else source
        stamp, version = now(), expected+1
        changed = db.execute('UPDATE records SET version=?,title=?,updated=? WHERE id=? AND version=?', (version,title or old['title'],stamp,rid,expected))
        if not changed.rowcount: raise HTTPException(409,'版本冲突')
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (rid,version,dump(content),source,stamp))
        if old['kind'] in ('image','asset','style') and old['content'].get('url')==content.get('url'):
            annotation=db.execute('SELECT version,items FROM annotations WHERE record_id=? AND image_version=?',(rid,expected)).fetchone()
            if annotation:
                db.execute('INSERT INTO annotations VALUES(?,?,?,?)',(rid,version,annotation['version'],annotation['items']))

        db.execute('UPDATE projects SET updated=? WHERE id=?',(stamp,pid))
        result=self.get(db,pid,rid)
        if hasattr(self,'graph_record_changed'): self.graph_record_changed(db,pid,result)
        return result

    def file(self, db, pid, name, data, mime):
        fid = uid()
        path = self.root/'files'/fid
        path.write_bytes(data)
        db.execute('INSERT INTO files VALUES(?,?,?,?)',(fid,pid,Path(name).name,mime))
        return f'/api/projects/{pid}/files/{fid}'
