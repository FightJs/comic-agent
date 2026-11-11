"""Build portable data-only comic Skills from audited repository resources."""
import hashlib
import json
from pathlib import Path
from backend.skills import SkillPackage


def build(root):
    root=Path(root);index=json.loads((root/'source-index.json').read_text())
    for resource in index['rules']+index.get('references',[]):
        if hashlib.sha256((root/resource['path']).read_bytes()).hexdigest()!=resource['sha256']:raise ValueError('source_hash: '+resource['path'])
    audited={r['path'] for r in index.get('references',[])}
    result={}
    for item in index['packages']:
        files={'SKILL.md':(root/'entries'/f"{item['id']}.md").read_text(),'references/workbench.md':(root/'workbench.md').read_text()}
        for rule in item['rules']:files[f'rules/{rule}.md']=(root/'rules'/f'{rule}.md').read_text()
        for path in item.get('references',[]):
            if path not in audited:raise ValueError('reference_not_audited: '+path)
            files[path]=(root/path).read_text()
        files['provenance.json']=json.dumps({'format':'comic-skill-migration/v1','source_entry':item['source_entry'],'source_entry_sha256':item['source_entry_sha256'],'rule_sources':[r for r in index['rules'] if Path(r['path']).stem in item['rules']],'reference_sources':[r for r in index.get('references',[]) if r['path'] in item.get('references',[])],'script_adaptations':index.get('script_adaptations',[]),'harness_metadata':item.get('harness_metadata'),'runtime_scripts_migrated':False,'semantic_vendor_verified':False},ensure_ascii=False,indent=2)
        body={'format':'comic-skill/v1','id':item['id'],'name':item['name'],'version':index['version'],'stages':item['stages'],'tags':['条漫','五件套','一致性','Pi迁移'],'entrypoint':'SKILL.md','files':files}
        SkillPackage.model_validate(body);result[item['id']]=body
    return result


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]/'resources/comic-skills'
    for name,body in build(root).items():(root/'packages'/f'{name}.json').write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
