"""Build a 10k-node/30k-edge fixture in the isolated review database only."""
import sys,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.store import Store,now
from backend import graph_store as gs
root=Path(__file__).resolve().parents[1]/'output'/'graph-review-data'
store=Store(root);started=time.perf_counter();pid='graph-scale'
with store.db() as db:
    gs.schema(db)
    if not db.execute('SELECT id FROM projects WHERE id=?',(pid,)).fetchone(): db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(pid,'规模验收 · 10000实体／30000关系',0,now(),now()))
    nodes=[gs.node({'id':f'n{i}','label':f'人物{i:05d}','type':'PERSON','important':i<30,'known_from':1}) for i in range(10000)]
    edges=[gs.edge({'id':f'e{i}_{step}','source':f'n{i}','target':f'n{(i+step)%10000}','relation':'关联','known_from':1}) for i in range(10000) for step in (1,7,31)]
    state=gs.empty();state['original']={'nodes':nodes,'edges':edges};gs.publish(store,db,pid,state,'隔离规模验收夹具')
print(json.dumps({'nodes':len(nodes),'edges':len(edges),'seed_seconds':round(time.perf_counter()-started,3)},ensure_ascii=False))
