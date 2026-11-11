"""Immutable Unicode document parses. Offsets always count Python code points."""
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from fastapi import HTTPException
from .store import uid, now, dump

MAX_UPLOAD = 128 * 1024 * 1024


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,project_id TEXT,title TEXT,file_id TEXT,record_id TEXT,parse_version INTEGER,encoding TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS document_parses(document_id TEXT,version INTEGER,text TEXT,chapters TEXT,warnings TEXT,created TEXT,PRIMARY KEY(document_id,version));
    CREATE INDEX IF NOT EXISTS documents_project ON documents(project_id);
    ''')


def chapters_for(text):
    found=[]; volume=None
    pattern=r'(?m)^[ \t]*(?:#{1,6}[ \t]+)?(第[零〇一二三四五六七八九十百千万两\d]+[章回节卷部][^\n\r]*|(?:Chapter|CHAPTER)\s+\d+[^\n\r]*)'
    for m in re.finditer(pattern,text):
        title=m.group(1).strip()
        if re.match(r'第.+[卷部]',title.split()[0]): volume=title
        found.append({'title':title,'start':m.start(),**({'volume':volume} if volume else {})})
    if not found: found=[{'title':'全文','start':0}]
    elif found[0]['start']>0: found.insert(0,{'title':'前言','start':0})
    return chapter_ranges(found,len(text))


def chapter_ranges(chapters,size):
    if not chapters or chapters[0].get('start')!=0: raise HTTPException(422,'章节必须从正文起点 0 开始')
    result=[]; previous=-1
    for i,c in enumerate(chapters):
        start=c.get('start'); title=c.get('title')
        if type(start) is not int or not previous<start<size or not isinstance(title,str) or not title.strip():
            raise HTTPException(422,'章节起点须严格递增且位于正文范围内，标题不能为空')
        result.append({'index':i+1,'title':title.strip(),'start':start,'end':chapters[i+1]['start'] if i+1<len(chapters) else size,**({'volume':c['volume']} if c.get('volume') else {})})
        previous=start
    return result


def parse_bytes(raw,title,encoding='auto'):
    suffix=Path(title).suffix.lower(); warnings=[]
    if suffix in ('.txt','.md'):
        if encoding not in ('auto','utf-8-sig','utf-8','gb18030'): raise HTTPException(422,'请选择 UTF-8 或 GB18030')
        text=None
        for codec in (['utf-8-sig','gb18030'] if encoding=='auto' else [encoding]):
            try:
                candidate=raw.decode(codec)
                if '\0' in candidate or any(ord(c)<32 and c not in '\r\n\t' for c in candidate): continue
                text=candidate; encoding=codec; break
            except UnicodeError: continue
        if text is None: raise HTTPException(422,'无法可靠解码，请指定编码后重试')
    elif suffix=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info=archive.getinfo('word/document.xml')
                if info.file_size>MAX_UPLOAD: raise ValueError()
                root=ET.fromstring(archive.read(info))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text='\n'.join(''.join(p.itertext()) if not p.findall('.//w:t',ns) else ''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns))
            encoding='unicode'
        except (ValueError,KeyError,zipfile.BadZipFile,ET.ParseError): raise HTTPException(422,'DOCX 文件无法解析')
    elif suffix=='.pdf':
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(raw))
            if reader.is_encrypted: raise ValueError()
            pages=[p.extract_text() or '' for p in reader.pages]
            text='\n'.join(pages); encoding='unicode'
            if any(not p.strip() for p in pages): warnings.append('部分 PDF 页面无可提取文字；扫描页需 OCR 后重新导入。')
        except Exception: raise HTTPException(422,'PDF 无法提取文字，请检查加密或使用 OCR 后导入')
    else: raise HTTPException(422,'支持 TXT、MD、DOCX 和 PDF')
    if not text.strip(): raise HTTPException(422,'文件没有可提取正文；扫描文件需先 OCR')
    if len(text)>12_000_000: raise HTTPException(413,'正文最多 1200 万字符')
    chapters=chapters_for(text)
    if len(chapters)==1: warnings.append('未识别章节标题，可手动校正章节切分。')
    return text,chapters,warnings,encoding


def parse_coverage(doc):
    incomplete=doc['status']=='waiting_ocr' or any('页面无可提取文字' in w for w in doc['warnings'])
    return {'document_id':doc['id'],'parse_version':doc['parse_version'],'title':doc['title'],'status':doc['status'],'complete':not incomplete,'available_chars':doc['char_count'],'warnings':doc['warnings'],'scope':'仅表示此上传文件的解析覆盖；不代表已读完正文或语义完整。'}


def get_document(store,db,pid,did,version=None,include_text=False):
    row=db.execute('SELECT * FROM documents WHERE id=? AND project_id=?',(did,pid)).fetchone()
    if not row: raise HTTPException(404,'文档不存在或不属于当前项目')
    version=row['parse_version'] if version is None else version
    p=db.execute('SELECT * FROM document_parses WHERE document_id=? AND version=?',(did,version)).fetchone()
    if not p: raise HTTPException(404,'解析版本不存在')
    chapters=json.loads(p['chapters'])
    value={'id':did,'title':row['title'],'parse_version':version,'status':'waiting_ocr' if any(w.startswith('[waiting_ocr]') for w in json.loads(p['warnings'])) else 'ready','char_count':len(p['text']),'chapter_count':len(chapters),'chapters':chapters,'warnings':json.loads(p['warnings'])}
    if include_text: value['_text']=p['text']
    return value


def save_parse(store,db,pid,did,text,chapters,warnings):
    row=db.execute('SELECT parse_version FROM documents WHERE id=? AND project_id=?',(did,pid)).fetchone()
    if not row: raise HTTPException(404,'文档不存在')
    version=row['parse_version']+1
    db.execute('INSERT INTO document_parses VALUES(?,?,?,?,?,?)',(did,version,text,dump(chapters),dump(warnings),now()))
    db.execute('UPDATE documents SET parse_version=? WHERE id=?',(version,did))
    return get_document(store,db,pid,did)


def import_document(store,db,pid,title,raw,encoding='auto',parsed=None):
    store.project(db,pid)
    text,chapters,warnings,encoding=parsed or parse_bytes(raw,title,encoding)
    url=store.file(db,pid,title,raw,'application/octet-stream'); did=uid()
    record=store.add(db,pid,'original',title,{'document_id':did,'parse_version':1,'char_count':len(text),'chapters':[{**c,'offset':c['start']} for c in chapters],'url':url,'encoding':encoding,'size':len(raw)},'import')
    db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',(did,pid,title,url.rsplit('/',1)[-1],record['id'],1,encoding,now()))
    db.execute('INSERT INTO document_parses VALUES(?,?,?,?,?,?)',(did,1,text,dump(chapters),dump(warnings),now()))
    return get_document(store,db,pid,did)


def chunks_for(chapters,size=3000,overlap=200):
    for chapter in chapters:
        start=chapter['start']
        while start<chapter['end']:
            end=min(chapter['end'],start+size)
            yield {'chapter':chapter['index'],'start':start,'end':end}
            if end==chapter['end']: break
            start=end-overlap


def migrate_legacy(store,db):
    """Keep historical versions immutable; attach compact metadata in a new current version."""
    rows=db.execute("SELECT r.id,r.project_id FROM records r LEFT JOIN documents d ON d.record_id=r.id WHERE r.kind='original' AND d.id IS NULL").fetchall()
    for row in rows:
        record=store.get(db,row['project_id'],row['id']); content=record['content']; text=content.get('text')
        if not isinstance(text,str) or not text.strip(): continue
        did=uid(); chapters=chapters_for(text); url=content.get('url',''); fid=url.rsplit('/',1)[-1]
        if not db.execute('SELECT id FROM files WHERE id=? AND project_id=?',(fid,row['project_id'])).fetchone():
            url=store.file(db,row['project_id'],record['title'],text.encode('utf-8'),'text/plain'); fid=url.rsplit('/',1)[-1]
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',(did,row['project_id'],record['title'],fid,record['id'],1,content.get('encoding','utf-8'),now()))
        db.execute('INSERT INTO document_parses VALUES(?,?,?,?,?,?)',(did,1,text,dump(chapters),dump(['已迁移旧版 TXT 原著；历史版本仍保留。']),now()))
        metadata={k:v for k,v in content.items() if k!='text'}
        metadata.update(document_id=did,parse_version=1,char_count=len(text),chapters=[{**c,'offset':c['start']} for c in chapters],url=url)
        store.save(db,row['project_id'],record['id'],record['version'],metadata,source=record['source'])
