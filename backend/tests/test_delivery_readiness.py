import json
import pytest
from backend.store import Store, dump


@pytest.fixture
def setup(tmp_path):
    store=Store(tmp_path)
    with store.db() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('p','test',0,'t','t'))
        db.execute('CREATE TABLE vision_reviews(id TEXT,project_id TEXT,manifest TEXT,status TEXT,report TEXT,created TEXT)')
        db.execute('CREATE TABLE image_jobs(id TEXT,project_id TEXT,status TEXT,payload TEXT,call_id TEXT)')
        db.execute('CREATE TABLE image_calls(id TEXT,project_id TEXT,status TEXT)')
    return store


def read(store, **kw):
    from backend.delivery_readiness import readiness
    with store.db() as db:
        before=db.total_changes
        value=readiness(store,db,'p',**kw)
        assert db.total_changes==before
        return value


def panel(store, number=1, source='manual'):
    with store.db() as db:
        return store.add(db,'p','script','secret正文',{'episode':1,'panel':number,'batch':1,'text':'SECRET'},source)


def image(store, script):
    with store.db() as db:
        r=store.add(db,'p','image','image',{'episode':1,'panel':script['content']['panel'],'script_id':script['id'],'script_version':1,'url':'/api/projects/p/files/f'},'mock')
        db.execute('INSERT OR IGNORE INTO files VALUES(?,?,?,?)',('f','p','secret.png','image/png'))
        for record in (script,r):
            db.execute('INSERT OR IGNORE INTO reviews VALUES(?,?,?,?,?,?,?)',(record['id'],record['id'],1,'approved','SECRET','manual','t'))
        return r


def report(store,script,img,*,version=1,issues=None):
    manifest={'images':[{'id':img['id'],'version':version,'head_version':version,'adopted':1,'review':'approved','source':'mock','file_id':'f','sha256':'fake'}], 'context':[{'id':script['id'],'version':1}], 'sources':[], 'source':'mock'}
    with store.db() as db:
        db.execute('INSERT INTO vision_reviews VALUES(?,?,?,?,?,?)',('v','p',dump(manifest),'completed',dump({'summary':'SECRET','issues':issues or []}),'t'))


def test_empty_scope_is_not_complete(setup):
    assert read(setup)['status']=='empty_scope'


def test_full_source_scope_includes_missing_image_and_hides_text(setup):
    panel(setup);panel(setup,2)
    value=read(setup)
    assert len(value['panels'])==2
    assert all('missing_image' in x['blockers'] for x in value['panels'])
    assert 'SECRET' not in json.dumps(value) and 'secret正文' not in json.dumps(value)


def test_exact_qa_and_human_review_required_mock_preserved(setup):
    s=panel(setup);i=image(setup,s)
    assert 'unobserved' in read(setup)['panels'][0]['blockers']
    report(setup,s,i)
    value=read(setup)
    assert value['status']=='ready'
    assert value['panels'][0]['vision']['source']=='mock'
    assert value['pixel_bytes_reverified'] is False


def test_old_report_is_stale_not_a_pass(setup):
    s=panel(setup);i=image(setup,s);report(setup,s,i)
    with setup.db() as db:
        setup.save(db,'p',i['id'],1,{**i['content'],'description':'changed'})
    assert 'stale_visual_report' in read(setup)['panels'][0]['blockers']


def test_issues_and_unknown_cancelled_call_block_delivery(setup):
    s=panel(setup);i=image(setup,s);report(setup,s,i,issues=[{'severity':'major','description':'SECRET'}])
    with setup.db() as db:
        db.execute('INSERT INTO image_calls VALUES(?,?,?)',('call','p','unknown'))
        db.execute('INSERT INTO image_jobs VALUES(?,?,?,?,?)',('j','p','cancelled',dump({'identity':'image:1:1'}),'call'))
    blockers=read(setup)['panels'][0]['blockers']
    assert 'unresolved_visual_issues' in blockers and 'unresolved_image_call' in blockers


def test_candidates_deleted_and_other_scope_do_not_count(setup):
    s=panel(setup)
    with setup.db() as db:
        setup.save(db,'p',s['id'],1,{**s['content'],'creation_candidate':True})
    assert read(setup)['status']=='empty_scope'
    assert read(setup,episode=2)['status']=='empty_scope'


def test_package_revision_and_report_reference_state_changes_block(setup):
    s=panel(setup);i=image(setup,s)
    with setup.db() as db:
        package=setup.add(db,'p','package','package',{'episode':1,'panel':1,'script_id':s['id'],'script_version':1})
        i=setup.save(db,'p',i['id'],1,{**i['content'],'package_id':package['id'],'package_version':1})
        db.execute('UPDATE records SET adopted=2 WHERE id=?',(i['id'],))
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',('rv2',i['id'],2,'approved','','mock','u'))
        setup.save(db,'p',package['id'],1,{**package['content'],'prompt':'changed'})
    assert 'image_package_mismatch' in read(setup)['panels'][0]['blockers']


def test_ambiguous_images_and_unapproved_sources_never_ready(setup):
    s=panel(setup);image(setup,s);image(setup,s)
    with setup.db() as db:
        db.execute("DELETE FROM reviews WHERE record_id=?",(s['id'],))
    blockers=read(setup)['panels'][0]['blockers']
    assert 'ambiguous_image' in blockers and 'source_not_approved' in blockers


def test_frozen_reference_review_changes_expire_report(setup):
    s=panel(setup);i=image(setup,s);report(setup,s,i)
    with setup.db() as db:
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',('later',i['id'],1,'rejected','','mock','z'))
    blockers=read(setup)['panels'][0]['blockers']
    assert 'stale_visual_report' in blockers and 'image_not_approved' in blockers
