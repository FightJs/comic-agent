"""Read-only database evidence checklist, never a whole-episode completion claim.

No files are opened: pixel hashes are retained by visual review, not reverified here.
"""
import json
from fastapi import HTTPException
from .store import is_primary
from .vision_grounding import sources_stale


def _source(value):
    return value if value in ('manual','ai','mock','import') else 'unknown'


def _ref(record):
    return {k:record[k] for k in ('id','version','adopted','review')} | {'source':_source(record['source'])}


def _manifest_current(store,db,pid,manifest):
    try:
        if sources_stale(store,db,pid,manifest.get('sources',[])):return False
        images=manifest['images']
        if not images:return False
        for index,fixed in enumerate(images):
            head=store.get(db,pid,fixed['id'])
            if not is_primary(head) or head['kind'] not in ('image','asset','style'):return False
            if any(head[k]!=fixed[k] for k in ('version','adopted','review','source')) or fixed['head_version']!=head['version']:return False
            fid=fixed['file_id']
            if head['content'].get('url')!=f'/api/projects/{pid}/files/{fid}':return False
            if not db.execute('SELECT id FROM files WHERE id=? AND project_id=?',(fid,pid)).fetchone():return False
            if index and (head['review']!='approved' or head['adopted']!=head['version']):return False
        for fixed in manifest['context']:
            head=store.get(db,pid,fixed['id'])
            if head['version']!=fixed['version'] or not is_primary(head):return False
    except (HTTPException,KeyError,TypeError,ValueError):return False
    return True


def readiness(store,db,pid,*,episode=None,batch=None):
    """Return whitelisted current-source panel evidence; SELECTs only.

    ``ready`` means the selected database checklist has no blockers. It does not
    assert supplier quality, actual pixel-file integrity, or full-story coverage.
    """
    for value in (episode,batch):
        if value is not None and (type(value) is not int or value<1):raise HTTPException(422,'话或批次须为正整数')
    store.project(db,pid)
    tables={r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    records=[store.get(db,pid,r['id']) for r in db.execute("SELECT id FROM records WHERE project_id=? AND kind IN ('script','image','package') ORDER BY id",(pid,))]
    scripts=[r for r in records if r['kind']=='script' and is_primary(r)]
    def in_scope(r):
        c=r['content'];e=c.get('episode');b=c.get('batch',(e-1)//10+1 if type(e) is int else None)
        return (episode is None or e==episode) and (batch is None or b==batch)
    scripts=[r for r in scripts if in_scope(r)]
    reports=[]
    if 'vision_reviews' in tables:
        for row in db.execute('SELECT id,manifest,status,report FROM vision_reviews WHERE project_id=? ORDER BY created DESC,id DESC',(pid,)):
            reports.append({**dict(row),'manifest':json.loads(row['manifest']),'report':json.loads(row['report']) if row['report'] else None})
    jobs=[]
    if 'image_jobs' in tables:
        for row in db.execute('SELECT id,status,payload,call_id FROM image_jobs WHERE project_id=?',(pid,)):
            call=db.execute('SELECT status FROM image_calls WHERE id=? AND project_id=?',(row['call_id'],pid)).fetchone() if 'image_calls' in tables else None
            if row['status'] in ('queued','running','unknown','received','interrupted') or row['status']=='cancelled' and call and call['status'] in ('submitting','unknown','received'):
                jobs.append(json.loads(row['payload']))
    panels=[]
    for script in scripts:
        c=script['content'];e,p=c.get('episode'),c.get('panel');blockers=[]
        slot_valid=all(type(n) is int and n>0 for n in (e,p))
        if not slot_valid:blockers.append('invalid_source_identity')
        peers=[r for r in scripts if r['content'].get('episode')==e and r['content'].get('panel')==p]
        if len(peers)>1:blockers.append('ambiguous_source')
        if script['review']!='approved':blockers.append('source_not_approved')
        if script['adopted']!=script['version']:blockers.append('source_not_adopted_current')
        images=[r for r in records if r['kind']=='image' and is_primary(r) and r['content'].get('episode')==e and r['content'].get('panel')==p] if slot_valid else []
        item={'episode':e if type(e) is int else None,'panel':p if type(p) is int else None,'script':_ref(script),'images':[_ref(r) for r in images],'vision':None,'blockers':blockers}
        if any(j.get('identity')==f'image:{e}:{p}' or j.get('image_content',{}).get('episode')==e and j.get('image_content',{}).get('panel')==p for j in jobs):blockers.append('unresolved_image_call')
        if not images:blockers.append('missing_image')
        elif len(images)>1:blockers.append('ambiguous_image')
        else:
            image=images[0];ic=image['content']
            if not ic.get('url'):blockers.append('missing_image_file')
            if image['review']!='approved':blockers.append('image_not_approved')
            if image['adopted']!=image['version']:blockers.append('image_not_adopted_current')
            if ic.get('script_id')!=script['id'] or ic.get('script_version')!=script['version']:blockers.append('image_source_mismatch')
            if ic.get('package_id'):
                package=next((r for r in records if r['id']==ic['package_id'] and r['kind']=='package'),None)
                if not package or not is_primary(package) or package['version']!=ic.get('package_version') or package['content'].get('script_id')!=script['id'] or package['content'].get('script_version')!=script['version']:
                    blockers.append('image_package_mismatch')
            if ic.get('input_stale'):blockers.append('image_inputs_stale')
            if ic.get('issues'):blockers.append('unresolved_image_issues')
            matches=[r for r in reports if r['manifest'].get('images') and r['manifest']['images'][0].get('id')==image['id']]
            exact=[r for r in matches if r['manifest']['images'][0].get('version')==image['version'] and _manifest_current(store,db,pid,r['manifest'])]
            if not exact:blockers.append('stale_visual_report' if matches else 'unobserved')
            else:
                report=exact[0];value=report['report'];issues=value.get('issues') if isinstance(value,dict) else None
                item['vision']={'id':report['id'],'status':report['status'] if report['status'] in ('prepared','queued','running','completed','unknown','invalid','cancelled','resolved','interrupted','received') else 'unknown','source':_source(report['manifest'].get('source')),'issue_count':len(issues) if isinstance(issues,list) else None}
                if report['status']!='completed' or not isinstance(issues,list):blockers.append('unobserved')
                elif issues:blockers.append('unresolved_visual_issues')
                if not any(ref.get('id')==script['id'] and ref.get('version')==script['version'] for ref in report['manifest'].get('context',[])):blockers.append('visual_source_not_observed')
        panels.append(item)
    panels.sort(key=lambda x:(x['episode'] or 0,x['panel'] or 0,x['script']['id']))
    ready=sum(not p['blockers'] for p in panels)
    return {'status':'empty_scope' if not panels else 'ready' if ready==len(panels) else 'blocked','scope':{'episode':episode,'batch':batch},'summary':{'source_panels':len(panels),'ready_panels':ready,'blocked_panels':len(panels)-ready},'pixel_bytes_reverified':False,'panels':panels}
