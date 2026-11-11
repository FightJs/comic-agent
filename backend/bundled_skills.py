"""Read shipped rule bundles; never install or execute them during discovery."""
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException
from .skills import SkillPackage

ROOT=Path(__file__).resolve().parents[1]/'resources/comic-skills/packages'


def bundled_packages():
    result={};total=0
    try:
        paths=sorted(ROOT.glob('*.json'))
        if not paths or len(paths)>50:raise ValueError('bundle_count')
        for path in paths:
            total+=path.stat().st_size
            if total>8*1024*1024:raise ValueError('bundle_size')
            pack=SkillPackage.model_validate_json(path.read_bytes()).model_dump()
            if any(Path(name).suffix not in ('.md','.json') for name in pack['files']):raise ValueError('rules_only')
            digest=hashlib.sha256(json.dumps(pack,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if digest in result:raise ValueError('duplicate_bundle')
            result[digest]=pack
    except (OSError,ValueError):raise HTTPException(503,'应用内置规则包缺失或无效；未安装，请核对应用资源')
    return result
