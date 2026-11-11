import pytest
from fastapi import HTTPException
from backend.app import create_app
from backend.agent_tools import ProjectTools, freeze_context


def fixture(tmp_path):
    app = create_app(tmp_path); store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','甲',0,'t','t')")
        db.execute("INSERT INTO projects VALUES('other','乙',0,'t','t')")
        record=store.add(db,'p','outline','第一话',{'text':'旧细纲'})
        foreign=store.add(db,'other','outline','秘密',{'text':'其他项目'})
        frozen=freeze_context(store,db,'p')
        store.save(db,'p',record['id'],1,{'text':'新细纲'})
    return store,record,foreign,frozen


def test_tools_read_only_frozen_versions_and_never_cross_project(tmp_path):
    store,record,foreign,frozen=fixture(tmp_path)
    tools=ProjectTools(store,'p',frozen)
    value=tools.call('project_query',{'action':'record','id':record['id']})
    assert value['version']==1 and value['content']['text']=='旧细纲'
    with pytest.raises(HTTPException): tools.call('project_query',{'action':'record','id':foreign['id']})
    with pytest.raises(HTTPException): tools.call('bash',{'command':'echo unsafe'})
    with pytest.raises(HTTPException): tools.call('project_query',{'action':'record','id':record['id'],'project_id':'other'})


def test_tool_budget_stops_instead_of_resetting(tmp_path):
    store,_,_,frozen=fixture(tmp_path)
    tools=ProjectTools(store,'p',frozen)
    for _ in range(50): tools.call('project_query',{'action':'catalog'})
    with pytest.raises(HTTPException) as error: tools.call('project_query',{'action':'catalog'})
    assert error.value.status_code==429


def test_novel_evidence_uses_frozen_parse_and_original_offsets(tmp_path):
    from backend.graph_documents import import_document,save_parse
    store,_,_,_=fixture(tmp_path)
    with store.db() as db:
        doc=import_document(store,db,'p','原著.txt','第一章\n林秋收到密信，离开故乡。'.encode())
        frozen=freeze_context(store,db,'p')
        save_parse(store,db,'p',doc['id'],'第二版不同正文',[],[])
    tools=ProjectTools(store,'p',frozen)
    result=tools.call('project_query',{'action':'search_novel','query':'密信'})
    evidence=result['matches'][0]
    assert evidence['parse_version']==1 and evidence['match_start']==8
    assert evidence['quote'][evidence['match_start']-evidence['start']:evidence['match_end']-evidence['start']]=='密信'
    source=tools.call('project_query',{'action':'source','id':doc['id'],'start':evidence['start']})
    assert source['text']=='第一章\n林秋收到密信，离开故乡。'
    with pytest.raises(HTTPException):tools.call('project_query',{'action':'source','id':'foreign'})


def test_explicit_session_refs_override_latest_snapshot(tmp_path):
    store,record,_,_=fixture(tmp_path)
    with store.db() as db:
        frozen=freeze_context(store,db,'p',[{'id':record['id'],'version':1}])
    assert ProjectTools(store,'p',frozen).call('project_query',{'action':'record','id':record['id']})['content']['text']=='旧细纲'


def test_explicit_original_record_locks_its_parse_even_after_reparse(tmp_path):
    from backend.graph_documents import import_document,save_parse
    store,_,_,_=fixture(tmp_path)
    with store.db() as db:
        doc=import_document(store,db,'p','原著.txt','第一章\n旧版密信'.encode())
        rid=db.execute('SELECT record_id FROM documents WHERE id=?',(doc['id'],)).fetchone()[0]
        save_parse(store,db,'p',doc['id'],'新版没有原文证据',[],[])
        frozen=freeze_context(store,db,'p',[{'id':rid,'version':1}])
    assert ProjectTools(store,'p',frozen).call('project_query',{'action':'search_novel','query':'密信'})['matches'][0]['parse_version']==1


def test_oversized_graph_tool_result_fails_before_protocol_transport(tmp_path):
    from backend import graph_store as gs
    store,_,_,_=fixture(tmp_path)
    with store.db() as db:
        state=gs.empty();state['original']['nodes']=[{'id':'large','label':'长摘要','summary':'x'*210000}]
        gs.publish(store,db,'p',state,'大资料边界')
        frozen=freeze_context(store,db,'p')
    with pytest.raises(HTTPException) as error:ProjectTools(store,'p',frozen).call('project_query',{'action':'graph'})
    assert error.value.status_code==422


def test_novel_tools_expose_fixed_parse_coverage_even_when_search_has_no_hits(tmp_path):
    from backend.graph_documents import import_document,chapters_for
    store,_,_,_=fixture(tmp_path)
    with store.db() as db:
        text='已经解析的一页'
        doc=import_document(store,db,'p','扫描.pdf',b'fixture',parsed=(text,chapters_for(text),['[waiting_ocr] 仍缺页'],'unicode'))
        frozen=freeze_context(store,db,'p')
    tools=ProjectTools(store,'p',frozen)
    source=tools.call('project_query',{'action':'source','id':doc['id']})
    assert source['coverage']['status']=='waiting_ocr' and source['coverage']['complete'] is False
    result=tools.call('project_query',{'action':'search_novel','query':'不存在的词'})
    assert result['matches']==[] and result['coverage'][0]['complete'] is False
    assert result['coverage'][0]['parse_version']==1
    catalog=tools.call('project_query',{'action':'catalog'})
    assert catalog['document_coverage'][0]['status']=='waiting_ocr'


def test_source_reads_remain_bounded_when_the_novel_has_thousands_of_chapters(tmp_path):
    from backend.graph_documents import import_document
    store,_,_,_=fixture(tmp_path)
    with store.db() as db:
        text='山'*60000
        chapters=[{'index':i+1,'title':'章节标题'*60,'start':i*20,'end':(i+1)*20} for i in range(3000)]
        doc=import_document(store,db,'p','长篇.txt',text.encode(),parsed=(text,chapters,[],'utf-8'))
        frozen=freeze_context(store,db,'p')
    value=ProjectTools(store,'p',frozen).call('project_query',{'action':'source','id':doc['id'],'start':10000})
    assert len(value['text'])==10000 and value['start']==10000
    assert len(value['chapters'])<=50 and value['chapters_truncated'] is True
    assert value['total_chapters']==3000
    assert all(c['start']<20000 and c['end']>10000 for c in value['chapters'])
