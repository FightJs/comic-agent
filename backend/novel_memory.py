"""Read-only, version-bound access to published novel summary units."""
import json
from fastapi import HTTPException
from .graph_documents import get_document,parse_coverage

KINDS={'chapter':'chapter_summary','volume':'volume_summary'}
POLICY='模型整理笔记，不是原文引文；需用source/search_novel核对事实和精确位置。同章或同卷可有多个单元，分页未读部分不得声称已通读。'


def freeze_summaries(store,db,pid,documents):
    result={}
    for did,version in documents.items():
        base={'parse_version':version,'status':'not_ready','job_id':None}
        doc=get_document(store,db,pid,did,version)
        if not parse_coverage(doc)['complete']:
            result[did]={**base,'reason':'incomplete_parse'};continue
        job=db.execute("SELECT * FROM graph_jobs WHERE project_id=? AND document_id=? AND parse_version=? AND kind='document' AND status='succeeded' AND stage='published' ORDER BY updated DESC,created DESC,id DESC LIMIT 1",(pid,did,version)).fetchone()
        if job:
            counts={r['kind']:r['n'] for r in db.execute("SELECT kind,COUNT(*) n FROM graph_units WHERE job_id=? AND status='succeeded' GROUP BY kind",(job['id'],))}
            incomplete=db.execute("SELECT 1 FROM graph_units WHERE job_id=? AND status<>'succeeded' LIMIT 1",(job['id'],)).fetchone()
            if not incomplete and all(counts.get(k,0)>0 for k in ('extract','chapter_summary','volume_summary')):
                result[did]={**base,'status':'ready','job_id':job['id'],'chapter_parts':counts['chapter_summary'],'volume_parts':counts['volume_summary']}
                continue
            base.update(reason='summary_units_missing')
        latest=db.execute("SELECT id,status,completed,total FROM graph_jobs WHERE project_id=? AND document_id=? AND parse_version=? AND kind='document' ORDER BY updated DESC,created DESC,id DESC LIMIT 1",(pid,did,version)).fetchone()
        result[did]={**base,'latest_job':dict(latest) if latest else None}
    return result


def read_summaries(store,db,pid,frozen,did,query,start,limit):
    documents=frozen['documents']
    if did is None:
        preferred=frozen.get('preferred_document')
        if preferred and preferred['id'] in documents:did=preferred['id']
        elif len(documents)==1:did=next(iter(documents))
    if not isinstance(did,str) or did not in documents:raise HTTPException(404,'请选择本次冻结原著的文档编号')
    doc=get_document(store,db,pid,did,documents[did])
    result={'document_id':did,'parse_version':documents[did],'coverage':parse_coverage(doc),'source':'model_summary','citation_policy':POLICY}
    binding=frozen.get('novel_memory',{}).get(did)
    if binding is None:return {**result,'status':'not_frozen','items':[],'reason':'此运行未冻结摘要，请新发消息或新建任务以绑定最新记忆'}
    if binding.get('status')!='ready':return {**result,**binding,'items':[],'reason':binding.get('reason') or '当前解析版本尚无已完整发布的原著整理任务'}
    jid=binding['job_id']
    job=db.execute("SELECT * FROM graph_jobs WHERE id=? AND project_id=? AND document_id=? AND parse_version=? AND kind='document' AND status='succeeded' AND stage='published'",(jid,pid,did,documents[did])).fetchone()
    if not job:return {**result,'job_id':jid,'status':'unavailable','items':[],'reason':'固定记忆任务不可用；不会切换到其他任务'}
    rid=db.execute('SELECT record_id FROM documents WHERE id=? AND project_id=?',(did,pid)).fetchone()['record_id']
    ref=frozen['records'].get(rid)
    original=store.get(db,pid,rid,ref['version'] if ref else None)
    result.update(job_id=jid,status='ready',source='mock' if original['source']=='mock' else 'model_summary',chapter_parts=binding['chapter_parts'],volume_parts=binding['volume_parts'])
    chapters={c['index']:c for c in json.loads(job['payload'])['chapters']}

    def item(row,offset=0,size=4000):
        payload=json.loads(row['payload']);text=json.loads(row['result'])['summary']
        volume=str(payload.get('volume',''));locator={'scope':'volume','volume':volume[:300],'volume_truncated':len(volume)>300}
        if row['kind']=='chapter_summary':
            chapter=chapters.get(payload.get('chapter'),{})
            title=str(payload.get('title',chapter.get('title','')))
            locator={'scope':'chapter','chapter':payload.get('chapter'),'title':title[:300],'title_truncated':len(title)>300,'start':chapter.get('start'),'end':chapter.get('end')}
        lo=min(offset,len(text));end=min(len(text),lo+size)
        return {'unit_id':row['unit_id'],'kind':row['kind'],'position':row['position'],'locator':locator,'summary':text[lo:end],'text_start':lo,'text_end':end,'total_chars':len(text),'truncated':lo>0 or end<len(text),'next_text_start':end if end<len(text) else None}

    if query.startswith('unit:'):
        row=db.execute("SELECT * FROM graph_units WHERE job_id=? AND unit_id=? AND kind IN ('chapter_summary','volume_summary') AND status='succeeded'",(jid,query[5:])).fetchone()
        if not row:raise HTTPException(404,'摘要单元不在本次固定记忆中')
        return {**result,**item(row,start,10000)}
    query=query or 'volume'
    prefix,separator,value=query.partition(':')
    selected_chapter=None;selected_volume=None
    if separator and prefix=='chapter':
        try:selected_chapter=int(value)
        except ValueError:raise HTTPException(422,'章节查询使用正整数解析序号')
        if selected_chapter<1:raise HTTPException(422,'章节查询使用正整数解析序号')
    elif separator and prefix=='volume':
        if not value.strip():raise HTTPException(422,'卷查询需要名称')
        selected_volume=value
    elif query not in KINDS and prefix!='search':raise HTTPException(422,'摘要查询使用volume、chapter、chapter:解析序号、volume:卷名、search:关键词或unit:单元编号')
    keyword=value if prefix=='search' and separator else None
    if prefix=='search' and (keyword is None or not keyword.strip()):raise HTTPException(422,'摘要检索需要非空关键词')
    kind=KINDS.get(prefix if separator else query)
    sql="SELECT * FROM graph_units WHERE job_id=? AND kind IN ('chapter_summary','volume_summary') AND status='succeeded'"+(' AND kind=?' if kind else '')+' ORDER BY position,unit_id'
    rows=db.execute(sql,(jid,kind) if kind else (jid,))
    items=[];total=0;size=min(limit,20)
    # Stream the rows: a long novel's notes never become one in-memory response.
    for row in rows:
        if selected_chapter is not None and json.loads(row['payload']).get('chapter')!=selected_chapter:continue
        if selected_volume is not None and json.loads(row['payload']).get('volume')!=selected_volume:continue
        if keyword is not None and keyword not in json.loads(row['result'])['summary']:continue
        if start<=total<start+size:items.append(item(row))
        total+=1
    next_start=start+len(items) if start+len(items)<total else None
    return {**result,'query':query,'items':items,'total':total,'start':start,'page_size':size,'next_start':next_start,'page_complete':next_start is None,'scope':'本页是固定任务的摘要单元；无命中不证明原著无此事实。'}
