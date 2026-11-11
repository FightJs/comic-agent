"""Read-only migrated ratio checks over exact frozen primary script order."""
import pytest
from fastapi import HTTPException
from backend.tests.test_agent_tools import fixture
from backend.agent_tools import freeze_context,ProjectTools

RATIOS=['9:16','3:4','4:5','1:1','9:16','3:4','4:5','9:16']

def setup(tmp_path,n=8):
    store,_,foreign,_=fixture(tmp_path)
    with store.db() as db:
        rows=[store.add(db,'p','script',f'格{i}',{'episode':1,'panel':i,'description':'剧情动作'}) for i in range(1,n+1)]
        candidate=store.add(db,'p','script','候选不进入全话',{'episode':1,'panel':99,'creation_candidate':True})
        frozen=freeze_context(store,db,'p',stage='package')
    return store,rows,foreign,frozen

def args(rows,ratios=RATIOS):return {'action':'frame_plan','id':rows[0]['id'],'plan':[{'id':row['id'],'ratio':ratio,'reason':'本格批准动作和必要接触适合该取景'} for row,ratio in zip(rows,ratios)]}

def test_read_only_checker_binds_full_frozen_order_and_keeps_old_source_versions(tmp_path):
    store,rows,_,frozen=setup(tmp_path)
    with store.db() as db:
        store.save(db,'p',rows[0]['id'],1,{**rows[0]['content'],'episode':2,'panel':20})
        store.add(db,'p','script','晚到新格',{'episode':1,'panel':9})
    tool=ProjectTools(store,'p',frozen)
    source=tool.call('project_query',{'action':'frame_plan','id':rows[0]['id']})
    assert [r['id'] for r in source['sources']]==[r['id'] for r in rows]
    result=tool.call('project_query',args(rows))
    assert result['valid'] and result['read_only'] and not result['adopted']
    assert result['statistics']['portrait_count']==7 and result['statistics']['minimum_portrait_count']==7
    assert result['sources'][0]['version']==1 and result['episode']==1
    with store.db() as db:
        assert store.get(db,'p',rows[0]['id'])['version']==2
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0

@pytest.mark.parametrize('change',['partial','reordered','duplicate','foreign','blank_reason','unknown_ratio','extra_key'])
def test_checker_refuses_partial_or_fabricated_plan(tmp_path,change):
    store,rows,foreign,frozen=setup(tmp_path);body=args(rows)
    if change=='partial':body['plan'].pop()
    if change=='reordered':body['plan'].reverse()
    if change=='duplicate':body['plan'][1]['id']=rows[0]['id']
    if change=='foreign':body['plan'][1]['id']=foreign['id']
    if change=='blank_reason':body['plan'][0]['reason']=' '
    if change=='unknown_ratio':body['plan'][0]['ratio']='2:3'
    if change=='extra_key':body['plan'][0]['approved']=True
    with pytest.raises(HTTPException):ProjectTools(store,'p',frozen).call('project_query',body)

def test_exactly_three_quarters_is_invalid_not_rounded_up(tmp_path):
    store,rows,_,frozen=setup(tmp_path,4)
    result=ProjectTools(store,'p',frozen).call('project_query',args(rows,['9:16','3:4','4:5','1:1']))
    assert not result['valid'] and result['statistics']['minimum_portrait_count']==4
    assert any(e['code']=='portrait_share' for e in result['errors'])

def test_checks_adjacency_balance_and_prefix_clumping(tmp_path):
    from backend.frame_plan import distribution
    assert any(e['code']=='adjacent' for e in distribution(['9:16']*8)['errors'])
    assert any(e['code']=='balance' for e in distribution(['9:16','3:4']*4)['errors'])
    # Totals balanced, portraits 24/30, alternation valid, but six nonportraits clump at end.
    sequence=['9:16','3:4','4:5']*8+['1:1','5:4','16:9']*2
    assert any(e['code']=='prefix' for e in distribution(sequence)['errors'])

def test_old_snapshot_and_other_actions_do_not_gain_plan_permission(tmp_path):
    store,rows,foreign,frozen=setup(tmp_path)
    frozen.pop('frame_plan_sources',None)
    with pytest.raises(HTTPException):ProjectTools(store,'p',frozen).call('project_query',args(rows))
    with pytest.raises(HTTPException):ProjectTools(store,'p',frozen).call('project_query',{'action':'record','id':rows[0]['id'],'plan':[]})
    with store.db() as db:other=freeze_context(store,db,'other')
    with pytest.raises(HTTPException):ProjectTools(store,'other',other).call('project_query',args(rows))


def test_actual_pi_sdk_calls_frame_plan_checker_without_writing(tmp_path,monkeypatch):
    import json,threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.app as module
    store,rows,_,_=setup(tmp_path);calls=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request)
            receipts=[json.loads(m['content']) for m in request['messages'] if m['role']=='tool']
            if not receipts:arguments={'action':'frame_plan','id':rows[0]['id']}
            elif len(receipts)==1:arguments={'action':'frame_plan','id':rows[0]['id'],'plan':[{'id':s['id'],'ratio':ratio,'reason':'合成已批准动作适合这个画幅'} for s,ratio in zip(receipts[0]['sources'],RATIOS)]}
            else:arguments=None
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'ratio-'+str(len(receipts)),'type':'function','function':{'name':'project_query','arguments':json.dumps(arguments)}}]} if arguments else {'role':'assistant','content':'已检查分布；未采用、未生图，内容与像素仍待核对。'}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for value,finish in [(delta,None),({},'tool_calls' if arguments else 'stop')]:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':value,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'synthetic-ratio-key')
    try:
        with store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
        with TestClient(create_app(tmp_path)) as c:
            sid=c.post('/api/projects/p/agent/sessions',json={'stage':'package'}).json()['id']
            sent=c.post(f'/api/projects/p/agent/sessions/{sid}/messages',json={'message':'只核对本话比例分布','expected_version':0}).json()
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                done=c.get('/api/projects/p/agent/runs/'+sent['id']).json()
                if done['status'] not in ('queued','running'):break
                time.sleep(.03)
            assert done['status']=='completed',done
            assert len(calls)==3
            result=json.loads([m for m in calls[2]['messages'] if m['role']=='tool'][-1]['content'])
            assert result['valid'] and result['read_only'] and not result['adopted']
            with store.db() as db:
                assert all(store.get(db,'p',r['id'])['version']==1 for r in rows)
                assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
    finally:server.shutdown();server.server_close();thread.join()


def test_mock_provenance_is_preserved_and_ambiguous_source_is_rejected(tmp_path):
    store,rows,_,_=setup(tmp_path)
    with store.db() as db:
        store.save(db,'p',rows[0]['id'],1,rows[0]['content'],source='mock')
        frozen=freeze_context(store,db,'p')
    result=ProjectTools(store,'p',frozen).call('project_query',args(rows))
    assert result['source']=='mock' and result['sources'][0]['source']=='mock'
    with store.db() as db:
        store.add(db,'p','script','重复主稿',rows[0]['content'])
        frozen=freeze_context(store,db,'p')
    with pytest.raises(HTTPException) as error:ProjectTools(store,'p',frozen).call('project_query',args(rows))
    assert error.value.status_code==409

@pytest.mark.parametrize('body',[{'action':'frame_plan','id':[]},{'action':'frame_plan','id':'a','plan':None}])
def test_invalid_tool_arguments_fail_closed(tmp_path,body):
    store,rows,_,frozen=setup(tmp_path)
    if body.get('plan','missing') is None:body={**body,'id':rows[0]['id']}
    with pytest.raises(HTTPException):ProjectTools(store,'p',frozen).call('project_query',body)


def test_malformed_primary_script_cannot_be_silently_excluded_from_whole_episode(tmp_path):
    store,rows,_,_=setup(tmp_path)
    with store.db() as db:
        store.add(db,'p','script','错误格号但仍为主稿',{'episode':1,'panel':'9'})
        frozen=freeze_context(store,db,'p')
    with pytest.raises(HTTPException) as error:ProjectTools(store,'p',frozen).call('project_query',args(rows))
    assert error.value.status_code==409


def test_explicit_historical_script_stays_in_frozen_source_instead_of_disappearing(tmp_path):
    store,rows,_,_=setup(tmp_path)
    with store.db() as db:
        store.save(db,'p',rows[0]['id'],1,{**rows[0]['content'],'description':'第二版不同文本'})
        frozen=freeze_context(store,db,'p',refs=[{'id':rows[0]['id'],'version':1}])
    result=ProjectTools(store,'p',frozen).call('project_query',args(rows))
    assert result['valid'] and len(result['sources'])==8 and result['sources'][0]['version']==1
