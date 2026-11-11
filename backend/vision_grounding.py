"""Frozen source excerpts and linked review rules for one constrained pixel check."""
from fastapi import HTTPException
from .graph_documents import get_document,parse_coverage
from .skills import freeze_stage_resources


def freeze_sources(store,db,pid,ranges):
    if not isinstance(ranges,(list,tuple)) or len(ranges)>10:raise HTTPException(422,'每次最多10段原著证据')
    result=[];total=0;seen=set()
    for ref in ranges:
        if not isinstance(ref,dict) or set(ref)!={'document_id','parse_version','start','end'} or not isinstance(ref['document_id'],str) or any(type(ref[k]) is not int for k in ('parse_version','start','end')):raise HTTPException(422,'原著证据需要文档、解析版本和字符范围；不接受客户端提供引文')
        doc=get_document(store,db,pid,ref['document_id'],ref['parse_version'],True)
        if not 0<=ref['start']<ref['end']<=doc['char_count'] or ref['end']-ref['start']>10000:raise HTTPException(422,'每段原著须为有效字符范围，最多10000字符；未截断')
        key=tuple(ref[k] for k in ('document_id','parse_version','start','end'))
        if key in seen:raise HTTPException(422,'原著证据范围重复')
        seen.add(key);total+=ref['end']-ref['start']
        if total>30000:raise HTTPException(422,'本次原著证据合计最多30000字符，请缩小范围')
        row=db.execute('SELECT record_id,parse_version FROM documents WHERE id=? AND project_id=?',(ref['document_id'],pid)).fetchone()
        original=store.get(db,pid,row['record_id'])
        result.append({**ref,'title':doc['title'],'quote':doc['_text'][ref['start']:ref['end']],'head_parse_version':row['parse_version'],'record_id':original['id'],'record_version':original['version'],'source':original['source'],'coverage':parse_coverage(doc)})
    return result


def freeze_review_rules(store,db,pid):
    return freeze_stage_resources(store,db,pid,'review')


def sources_stale(store,db,pid,sources):
    for source in sources:
        row=db.execute('SELECT parse_version FROM documents WHERE id=? AND project_id=?',(source['document_id'],pid)).fetchone()
        if not row or row['parse_version']!=source['head_parse_version']:return True
        if store.get(db,pid,source['record_id'])['version']!=source['record_version']:return True
    return False


def validate_citations(citations,sources):
    if not isinstance(citations,list) or len(citations)>10:raise ValueError('citations')
    for citation in citations:
        if not isinstance(citation,dict) or set(citation)!={'source','start','end','quote'} or any(type(citation[k]) is not int for k in ('source','start','end')) or not isinstance(citation['quote'],str) or not 1<=len(citation['quote'])<=2000:raise ValueError('citation')
        n=citation['source']
        if not 1<=n<=len(sources):raise ValueError('source_index')
        fixed=sources[n-1];start,end=citation['start'],citation['end']
        if not fixed['start']<=start<end<=fixed['end'] or fixed['quote'][start-fixed['start']:end-fixed['start']]!=citation['quote']:raise ValueError('source_quote')
