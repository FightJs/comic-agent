"""MinerU Cloud v4 and local HTTP adapters. Signed transfers never receive user keys."""
import asyncio
import io
import json
import zipfile
from urllib.parse import urlparse
import httpx


class ParsePaused(Exception): pass


def safe_url(value):
    if not isinstance(value,str) or urlparse(value).scheme not in ('http','https'): raise ValueError('解析服务下载地址无效')
    return value


async def parse_pdf(raw,title,config,transport,checkpoint,save_checkpoint,expected_pages=0):
    base=config['url'].rstrip('/'); auth={'Authorization':'Bearer '+config['secret']}
    async with httpx.AsyncClient(transport=transport,timeout=120,follow_redirects=False) as client:
        if '/api/v4' not in base and not base.endswith('/file-urls/batch'):
            url=base if base.endswith('/file_parse') else base+'/file_parse'
            response=await client.post(url,headers=auth,files={'files':(title,raw,'application/pdf')},data={'return_md':'true','return_middle_json':'true','return_content_list':'true','backend':config.get('model') or 'pipeline'})
            response.raise_for_status(); values=response.json().get('results',{})
            if isinstance(values,dict): values=list(values.values())
            blocks=[]
            for value in values:
                if not isinstance(value,dict): continue
                content=value.get('content_list',[])
                if isinstance(content,str): content=json.loads(content)
                if isinstance(content,list): blocks.extend(content)
            pages={b.get('page_idx') for b in blocks if isinstance(b,dict) and type(b.get('page_idx')) is int}
            if expected_pages and not set(range(expected_pages))<=pages: raise ValueError('本地 MinerU 未提供完整 content_list 页证据；禁止发布不完整正文')
            lines=[]
            for block in blocks:
                if not isinstance(block,dict): continue
                for key in ('text','table_body','image_caption','table_caption','equation'):
                    value=block.get(key)
                    if isinstance(value,str) and value.strip(): lines.append(value)
                    elif isinstance(value,list): lines.extend(v for v in value if isinstance(v,str))
            text='\n'.join(lines)
            if not text.strip(): raise ValueError('解析服务未返回完整正文块')
            return text,['正文经 MinerU 本地接口解析/OCR；请核对识别结果和章节。']
        base=base.removesuffix('/file-urls/batch')
        if not checkpoint.get('batch_id'):
            response=await client.post(base+'/file-urls/batch',headers=auth,json={'enable_table':True,'enable_formula':True,'language':'ch','files':[{'name':title,'is_ocr':True}]})
            response.raise_for_status(); result=response.json()
            if result.get('code')!=0: raise ValueError('MinerU 提交失败')
            data=result.get('data',{}); values=data.get('file_urls') or []
            if not data.get('batch_id') or not values: raise ValueError('MinerU 上传信息不完整')
            entry=values[0]; url=entry if isinstance(entry,str) else entry.get('url') or entry.get('upload_url') or entry.get('presigned_url')
            checkpoint.update(batch_id=data['batch_id'],upload_url=safe_url(url),uploaded=False)
            save_checkpoint(checkpoint)
        if not checkpoint.get('uploaded'):
            response=await client.put(safe_url(checkpoint['upload_url']),content=raw)
            response.raise_for_status(); checkpoint['uploaded']=True; save_checkpoint(checkpoint)
        result=checkpoint.get('result')
        for _ in range(600):
            save_checkpoint(checkpoint) # checks pause/cancel between remote steps
            if result: break
            response=await client.get(base+'/extract-results/batch/'+str(checkpoint['batch_id']),headers=auth)
            response.raise_for_status(); body=response.json()
            if body.get('code')!=0: raise ValueError('MinerU 轮询失败')
            items=body.get('data',{}).get('extract_result') or []
            if items:
                item=items[0]
                if item.get('state')=='failed':
                    checkpoint.clear(); save_checkpoint(checkpoint); raise ValueError('MinerU 任务失败')
                if item.get('state')=='done':
                    result=item.get('result') or item; checkpoint['result']=result; save_checkpoint(checkpoint); break
            await asyncio.sleep(1)
        if not result: raise ValueError('MinerU 解析超时；远端批次已保留供手动继续')
        blocks=None
        if result.get('content_list_url'):
            response=await client.get(safe_url(result['content_list_url']));response.raise_for_status();blocks=response.json()
        else:
            response=await client.get(safe_url(result.get('full_zip_url') or result.get('zip_url')));response.raise_for_status()
            if len(response.content)>128*1024*1024: raise ValueError('解析压缩包过大')
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                info=next((v for v in archive.infolist() if v.filename.endswith('content_list.json')),None)
                if not info or info.file_size>128*1024*1024: raise ValueError('解析包缺少 content_list')
                blocks=json.loads(archive.read(info))
        if not isinstance(blocks,list): raise ValueError('解析块格式无效')
        pages={b.get('page_idx') for b in blocks if isinstance(b,dict) and type(b.get('page_idx')) is int}
        if expected_pages and not set(range(expected_pages))<=pages: raise ValueError('MinerU 返回页不完整；禁止丢弃缺页后继续抽取')
        lines=[]
        for block in blocks:
            if not isinstance(block,dict): continue
            for key in ('text','table_body','image_caption','table_caption','equation'):
                value=block.get(key)
                if isinstance(value,str) and value.strip(): lines.append(value)
                elif isinstance(value,list): lines.extend(v for v in value if isinstance(v,str))
        text='\n'.join(lines)
        if not text.strip(): raise ValueError('MinerU 未返回可提取正文')
        return text,['正文经 MinerU Cloud 解析/OCR；所有原始页已核验返回，请核对识别结果。']
