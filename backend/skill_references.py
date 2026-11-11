"""Data-only Markdown references, with no network or filesystem resolution."""
import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import unquote,urlsplit

ID=r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}'
VERSION=r'[a-zA-Z0-9._-]{1,40}'

def safe_path(path):
    p=PurePosixPath(path)
    if not path or any(ord(c)<32 for c in path) or len(path)>200 or '\\' in path or ':' in path or p.is_absolute() or str(p)!=path or any(v in ('.','..') or v.startswith('.') for v in p.parts):raise ValueError('unsafe_path')

def links(text):
    tick=chr(96)
    operational=re.sub(tick*3+r'[\s\S]*?'+tick*3+r'|~~~[\s\S]*?~~~','',text)
    operational=re.sub(tick+r'[^'+tick+r'\n]*'+tick,'',operational)
    return [m.group(1) or m.group(2) for m in re.finditer(r'\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))[^)]*\)',operational)]

def cross_reference(target):
    parsed=urlsplit(target)
    if parsed.scheme!='skill':return None
    if parsed.query or parsed.netloc.count('@')!=1:raise ValueError('invalid_skill_reference')
    identity,version=parsed.netloc.split('@')
    if not re.fullmatch(ID,identity) or not re.fullmatch(VERSION,version):raise ValueError('invalid_skill_reference')
    path=unquote(parsed.path[1:] if parsed.path.startswith('/') else parsed.path)
    safe_path(path)
    return {'id':identity,'version':version,'path':path}

def local_reference(source,target):
    if urlsplit(target).scheme or target.startswith('#'):return None
    path=unquote(target.split('#',1)[0])
    return posixpath.normpath(posixpath.join(posixpath.dirname(source),path)) if path else None
