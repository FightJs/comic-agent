"""Persist cooperative pause intent; runtime checkpoints decide whether it is clean."""
from pydantic import BaseModel,ConfigDict
from .store import now

class PauseIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS pi_pause_requests(kind TEXT,target_id TEXT,requested TEXT,PRIMARY KEY(kind,target_id))')

def requested(db,kind,target_id):
    return db.execute('SELECT 1 FROM pi_pause_requests WHERE kind=? AND target_id=?',(kind,target_id)).fetchone() is not None

def mark(db,kind,target_id):
    db.execute('INSERT OR IGNORE INTO pi_pause_requests VALUES(?,?,?)',(kind,target_id,now()))

def clear(db,kind,target_id):
    db.execute('DELETE FROM pi_pause_requests WHERE kind=? AND target_id=?',(kind,target_id))
