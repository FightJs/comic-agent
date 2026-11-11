"""Disposable local UI review fixture; never reads real credentials or project data.
Run: .venv/bin/python scripts/pi_review_server.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
import backend.app as module
from backend.graph_documents import import_document

class FixtureVault:
    def get_password(self,*args): return 'ui-fixture-key'
    def set_password(self,*args): pass

class Provider(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path.startswith('/v1/images/'):
            import base64
            raw=self.rfile.read(int(self.headers['Content-Length']))
            if '【慢速生图验收】'.encode() in raw:time.sleep(4)
            if '【整组慢速验收】'.encode() in raw:time.sleep(12)
            if '【未知生图验收】'.encode() in raw:
                self.send_response(500);self.end_headers();return
            from backend.simulation import demo_image
            body=json.dumps({'data':[{'b64_json':base64.b64encode(demo_image(0)).decode()}]}).encode()
            try:
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('x-request-id','local-image-fixture');self.end_headers();self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages=request['messages'];last_user=max(i for i,m in enumerate(messages) if m['role']=='user')
        content=messages[last_user].get('content','');instruction=content if isinstance(content,str) else ''.join(v.get('text','') for v in content)
        if '【未知视觉验收】' in instruction or '【失败设置验收】' in instruction:
            self.send_response(500);self.end_headers();return
        has_tool=any(m['role']=='tool' for m in messages[last_user+1:])
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        def send(delta,reason=None):
            chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'ui-fixture','choices':[{'index':0,'delta':delta,'finish_reason':reason}]}
            self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode());self.wfile.flush()
        try:
            if '【未决暂停验收】' in instruction:
                calls=[{'index':i,'id':'pending-limit-'+str(i),'type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}} for i in range(51)]
                send({'role':'assistant','tool_calls':calls});send({},'tool_calls')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【三套画风验收】' in instruction:
                receipts=[json.loads(m['content']) for m in messages[last_user+1:] if m['role']=='tool']
                last=receipts[-1] if receipts else None
                action=None
                if last is None:action=('project_query',{'action':'catalog'})
                elif 'records' in last:action=('project_query',{'action':'source','id':last['preferred_document']['id']})
                elif 'document_id' in last and 'text' in last:
                    catalog=next(r for r in receipts if 'records' in r)
                    outline=next(r for r in catalog['records'] if r['kind']=='outline')
                    action=('project_query',{'action':'record','id':outline['id']})
                elif last.get('kind')=='outline':
                    source=next(r for r in receipts if 'document_id' in r and 'text' in r)
                    body={'title':'隔离三套画风测试','outline_id':last['id'],'representative':{'character':'林秋','appearance':'成年，深色外套，短发；补充外观待人工核对','scene':'故乡','setting':'雨夜街道与街灯，同一场景结构','action':'雨夜归乡，与沈宁相遇'},'source_ranges':[{k:source[k] for k in ('document_id','parse_version','start','end')}],'directions':[{'name':name,'line':line,'proportions':'自然人体比例','color':color,'shadow':shadow} for name,line,color,shadow in [('清晰线条','均匀清晰的二维线条','低饱和冷暖对比','简化平涂阴影'),('细腻线条','细线和少量排线','克制的灰蓝色','细腻分层阴影'),('粗犷线条','粗细变化的轮廓线','有限双色点缀','大块明暗')]]}
                    if '【整组慢速验收】' in instruction:body['representative']['setting']+='【整组慢速验收】'
                    action=('propose_style_tests',body)
                if action:
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'style-trio-'+str(len(receipts)),'type':'function','function':{'name':action[0],'arguments':json.dumps(action[1],ensure_ascii=False)}}]});send({},'tool_calls')
                else:
                    time.sleep(8)  # QA-only window to inspect a saved group before reply completion.
                    send({'role':'assistant','content':'三套同组测试方案已保存，尚未生图。共有外观补充与画风效果须人工核对；请分别预览和明确授权。' if last and last.get('id') else '方案未保存，请核对原著及细纲审核，未生图。'});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【自然完成暂停验收】' in instruction:
                time.sleep(4)
                send({'role':'assistant','content':'【隔离自然完成】在途文字已完整返回，原稿保持不变。'});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【手动暂停验收】' in instruction:
                if not has_tool and not instruction.startswith('本次由用户明确授权'):
                    time.sleep(float(os.environ.get('PI_REVIEW_MANUAL_PAUSE_DELAY','4')) if '固定输入：\n' in instruction else 4)
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'manual-pause-catalog','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                else:
                    value={'patch':{'description':'【隔离手动续接候选】保留原话格身份，只修改描述。'}} if '固定输入：\n' in instruction else '【隔离手动续接】原任务已完整返回，未修改原稿或生图；本机替身只验证暂停和明确续接。'
                    send({'role':'assistant','content':json.dumps(value,ensure_ascii=False) if isinstance(value,dict) else value});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【选段验收】' in instruction:
                if '【慢速选段】' in instruction:time.sleep(4)
                if not has_tool:
                    found=re.search(r'"id": "([0-9a-f]{32})", "kind": "(outline|skeleton)"',instruction)
                    if found:
                        change={'target':'record','id':found.group(1),'patch':{'text':'【隔离选段候选】保留动机😀'}}
                        send({'role':'assistant','tool_calls':[{'index':0,'id':'selection-proposal','type':'function','function':{'name':'propose_changes','arguments':json.dumps({'title':'隔离精确选段候选','changes':[change]})}}]});send({},'tool_calls')
                    else:send({'role':'assistant','content':'未找到固定文档，不提出候选。'});send({},'stop')
                else:
                    send({'role':'assistant','content':'选段候选已保存，尚未改动正文；请核对后明确采用。'});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【AI生图方案验收】' in instruction:
                kind='asset' if '阶段：asset' in instruction else 'style'
                if not has_tool:
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'image-plan-catalog','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                else:
                    receipt=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
                    if 'records' in receipt:
                        args={'title':'隔离AI生图方案','prompt':'【隔离AI方案】保持原人物身份、衣装与线条，夜景柔和光照，不改变目标身份。','category':'人物'}
                        target=next((r for r in receipt['records'] if r['kind']==kind and r['id'] in instruction),None) or next((r for r in receipt['records'] if r['kind']==kind),None)
                        if target and '新建' not in instruction.rsplit('用户要求：\n',1)[-1]:args['target_id']=target['id']
                        send({'role':'assistant','tool_calls':[{'index':0,'id':'image-plan-proposal','type':'function','function':{'name':'propose_image','arguments':json.dumps(args)}}]});send({},'tool_calls')
                    else:
                        send({'role':'assistant','content':'生图方案已保存，未修改原图，未调用图像模型；请先核对预览，再确认生成。' if receipt.get('status')=='pending' and receipt.get('id') else '生图方案未保存，请核对工具错误和本次附加目标，未调用图像模型。'});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【跨包引用验收】' in instruction and not instruction.startswith('{"snapshot"'):
                if not has_tool:
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'cross-catalog','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                else:
                    receipt=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
                    if 'skills' in receipt:
                        selected=next((info for info in receipt['skills'] if info['id']=='cross-flow'),None)
                        if selected:
                            send({'role':'assistant','tool_calls':[{'index':0,'id':'cross-resource','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'skill','id':selected['hash'],'query':'skill://cross-library@1.0/rules/common.md'})}}]});send({},'tool_calls')
                        else:send({'role':'assistant','content':'本次未冻结跨包主流程，请先明确启用主包及精确依赖版本。'});send({},'stop')
                    else:
                        send({'role':'assistant','content':'【隔离跨包读取】'+receipt['text']+' 仅按固定依赖读取资料，尚未修改成品。' if 'text' in receipt else '【隔离跨包未读取】请核对原工具错误，未宣称读取成功。'});send({},'stop')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【生产额度暂停验收】' in instruction:
                if instruction.startswith('本次由用户明确授权'):
                    send({'role':'assistant','content':json.dumps({'patch':{'description':'【隔离生产续接】保留原话格身份的完整候选正文。'}},ensure_ascii=False)});send({},'stop')
                else:
                    count=sum(m['role']=='tool' for m in messages[last_user+1:])
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'production-limit-'+str(count),'type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                self.wfile.write(b'data: [DONE]\n\n');return
            if '【额度暂停验收】' in instruction:
                if instruction.startswith('本次由用户明确授权'):
                    send({'role':'assistant','content':'【隔离续接完成】已按原固定任务继续，尚未采用或生图。'});send({},'stop')
                else:
                    count=sum(m['role']=='tool' for m in messages[last_user+1:])
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'limit-query-'+str(count),'type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                self.wfile.write(b'data: [DONE]\n\n');return
            if instruction.startswith('{"snapshot"'):
                fixed=json.loads(instruction);snapshot=fixed['snapshot'];user=fixed['user'];actions=[]
                if '【内置规则验收】' in user:
                    if not has_tool:
                        args={'source':'bundled','query':'无此规则' if '空结果' in user else '', 'limit':10}
                        send({'role':'assistant','tool_calls':[{'index':0,'id':'bundled-catalog','type':'function','function':{'name':'setup_catalog','arguments':json.dumps(args)}}]});send({},'tool_calls')
                    else:
                        receipt=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'));picks=receipt.get('items',[])
                        actions=[{'kind':'install_skill','attachment':item['handle']} for item in picks]
                        if picks and snapshot.get('project_id') and '启用' in user:actions.append({'kind':'select_skills','handles':[item['handle'] for item in picks]})
                        send({'role':'assistant','content':json.dumps({'reply':'【隔离内置规则】只提出首版规则包安装候选，尚未安装或启用，完整迁移未完成。','actions':actions},ensure_ascii=False)});send({},'stop')
                    self.wfile.write(b'data: [DONE]\n\n');return
                if '【流程检索验收】' in user:
                    if not has_tool:
                        args={'query':'未存在流程' if '空结果' in user else '隔离目录流程','start':50 if '分页' in user else 0,'limit':2}
                        send({'role':'assistant','tool_calls':[{'index':0,'id':'setup-catalog','type':'function','function':{'name':'setup_catalog','arguments':json.dumps(args)}}]});send({},'tool_calls')
                    else:
                        receipt=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
                        picks=receipt.get('items',[])
                        value={'reply':'【隔离目录查询】已按需检索固定流程库；未执行安装或启用。','actions':[{'kind':'select_skills','handles':['installed:'+picks[0]['hash']]}] if picks and snapshot.get('project_id') else []}
                        send({'role':'assistant','content':json.dumps(value,ensure_ascii=False)});send({},'stop')
                    self.wfile.write(b'data: [DONE]\n\n');return
                if '【慢速设置验收】' in user:time.sleep(4)
                for attachment in snapshot['attachments']:
                    actions.append({'kind':'apply_config' if attachment['type']=='config' else 'install_skill','attachment':attachment['handle']})
                if snapshot.get('project_id') and '启用' in user:
                    handles=[a['handle'] for a in snapshot['attachments'] if a['type']=='skill']
                    if not handles and snapshot.get('catalog'):handles=['installed:'+snapshot['catalog'][0]['hash']]
                    actions.append({'kind':'select_skills','handles':handles})
                value={'reply':'【隔离设置助手】已核对本次脱敏配置和所附包。以下仅为建议，尚未应用或安装；请逐项核对。','actions':actions}
                send({'role':'assistant','content':'【隔离无效设置返回】' if '【无效设置验收】' in user else json.dumps(value,ensure_ascii=False)});send({},'stop')
            elif isinstance(content,list) and any(v.get('type')=='image_url' for v in content):
                if '【慢速视觉验收】' in instruction:time.sleep(4)
                count=sum(v.get('type')=='image_url' for v in content)
                value={'summary':'【隔离视觉替身】仅用于界面与协议验收，不证明画质判断。','issues':[{'severity':'major','category':'identity','description':'【替身问题】请核对人物服装','evidence':'图1中部的服装区域需人工与批准参考对照；这是固定测试报告。','images':list(range(1,min(count,2)+1)),'region':[.15,.2,.5,.4]}]}
                if '\n' in instruction:
                    try:fixed=json.loads(instruction.split('\n',1)[1])
                    except ValueError:fixed={}
                    if fixed.get('sources'):
                        source=fixed['sources'][0];quote=source['quote'][:40]
                        value['issues'][0]['source_evidence']=[{'source':1,'start':source['start'],'end':source['start']+len(quote),'quote':quote}]
                    if '【自动返修验收】' in instruction:
                        target_prompt=(fixed.get('images') or [{}])[0].get('prompt','')
                        value={'summary':'【隔离自动检查】返修后仍须人工核对；此为固定替身输出。','issues':[]} if '【宿主固定：仅一轮严重剧情返修】' in target_prompt else {'summary':'【隔离自动检查】触发一次剧情返修的固定报告。','issues':[{'severity':'critical','category':'story','description':'【替身剧情问题】递信动作缺失','evidence':'图1人物的手部未表现固定提示词中的递信动作；仅为流程验收固定报告。','images':[1],'region':[.2,.2,.4,.4]}]}
                send({'role':'assistant','content':'【格式错误视觉替身】' if '【无效视觉验收】' in instruction else json.dumps(value,ensure_ascii=False)});send({},'stop')
            elif 'TASK:' in instruction and '固定输入：\n' not in instruction:
                value={'nodes':[],'edges':[],'summary':'【隔离图谱摘要】'} if 'TASK:extract' in instruction else {'merges':[],'aliases':[]} if 'TASK:consolidate' in instruction else {'summary':'【隔离图谱摘要】'}
                send({'role':'assistant','content':json.dumps(value,ensure_ascii=False)});send({},'stop')
            elif '固定输入：\n' in instruction:
                context=json.loads(instruction.split('固定输入：\n',1)[1].split('\n本次启用流程规则：',1)[0])
                if '【慢速验收】' in context.get('instruction',''):time.sleep(4)
                if '【失败验收】' in context.get('instruction',''):
                    send({'role':'assistant','content':'【隔离故障】不是合法结构'});send({},'stop')
                elif not has_tool:
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'production-catalog','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]});send({},'tool_calls')
                else:
                    op=context['operation']
                    def panel(n):return {'panel':n,'characters':'林秋、沈宁','scene':'故乡街头','weather':'雨','time':'夜','shot':'中景','camera':'平视','description':f'【隔离生产候选】第{n}格：林秋与沈宁在街头核对密信。','dialogue':'信是谁寄来的？','sfx':'雨声','note':'保留人物身份；此为本机替身返回'}
                    value={'panels':[panel(1),panel(2)]} if op=='range' else {} if op=='document' else {'scene_prompt':'【隔离生产候选】雨夜街头','content_prompt':'林秋核对密信','position_prompt':'林秋在左，沈宁在右','shot_prompt':'中景平视','constraints':'保留人物身份与服装'} if op=='package' else {'patch':{'description':'【隔离修改候选】林秋收起密信，望向故乡街头。'}} if context['snapshots'][0]['kind']=='script' else {'patch':{'shot_prompt':'【隔离修改候选】平视中景，增强信件焦点'}}
                    if op=='document':value={'title':'【隔离候选】全书骨架','sections':[{'heading':'主线与转折','text':'【隔离文档候选】围绕归乡与密信组织人物动机。\n此段为本机替身返回，不是模型语义验收。'},{'heading':'人物弧线','text':'林秋从犹豫到主动核对线索。'}]} if context['document_kind']=='skeleton' else {'title':'【隔离候选】分集细纲','entries':[{'episode':2,'title':'密信','text':'【隔离细纲候选】林秋与沈宁核对密信。','source_range':'第二章'},{'episode':3,'title':'街头','text':'二人在故乡街头寻找线索。','source_range':'第二章'}]}
                    send({'role':'assistant','content':json.dumps(value,ensure_ascii=False)});send({},'stop')
            elif ('【新增脚本验收】' in instruction or '【删除脚本验收】' in instruction) and not has_tool:
                found=re.search(r'"id": "([0-9a-f]{32})", "kind": "script"',instruction)
                if not found:
                    send({'role':'assistant','content':'请附加一个当前脚本。'});send({},'stop')
                else:
                    target='script_create' if '【新增脚本验收】' in instruction else 'script_delete'
                    patch={'panel':2,'description':'【隔离新增脚本】林秋停步回头，沈宁注视密信。','dialogue':'信从哪里来？'} if target=='script_create' else {'reason':'【隔离删除】镜头重复，保留历史版本。'}
                    change={'target':target,'id':found.group(1),'patch':patch}
                    send({'role':'assistant','tool_calls':[{'index':0,'id':'crud-'+str(len(messages)),'type':'function','function':{'name':'propose_changes','arguments':json.dumps({'title':'隔离脚本增删候选','changes':[change]})}}]});send({},'tool_calls')
            elif '【修改验收】' in instruction and not has_tool:
                found=re.search(r'"id": "([0-9a-f]{32})", "kind": "(outline|skeleton|script|package|style|asset)"',instruction)
                if found:
                    rid,kind=found.groups()
                    patch={'text':'第1话 雨夜重逢\n【隔离验收候选】保留人物动机，增强转折。'} if kind in ('outline','skeleton') else {'description':'【隔离验收候选】雨夜街头重逢，保留人物与场景身份。'} if kind in ('script','style','asset') else {'shot_prompt':'【隔离验收候选】中景平视，人物站位清楚。'}
                    change={'target':'record','id':rid,'patch':patch}
                else:change={'target':'graph_node','id':'fixture-person','patch':{'summary':'【隔离验收候选】林秋回乡后收到密信，进一步核对其动机。'}}
                send({'role':'assistant','tool_calls':[{'index':0,'id':'proposal-'+str(len(messages)),'type':'function','function':{'name':'propose_changes','arguments':json.dumps({'title':'隔离验收修改候选','changes':[change]})}}]})
                send({},'tool_calls')
            elif not has_tool:
                send({'role':'assistant','tool_calls':[{'index':0,'id':'catalog-'+str(len(request['messages'])),'type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]})
                send({},'tool_calls')
            else:
                for part in ['【隔离验收替身答复】\n','已查询本次项目资料目录。\n','建议先核对人物动机，再调整当前话的转折。\n','这只是讨论建议，尚未修改文档或生成图片。']:
                    send({'role':'assistant','content':part});time.sleep(.8)
                send({},'stop')
            self.wfile.write(b'data: [DONE]\n\n')
        except (BrokenPipeError,ConnectionResetError): pass
    def log_message(self,*args): pass

if __name__=='__main__':
    provider=ThreadingHTTPServer(('127.0.0.1',18767),Provider)
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    module.vault=FixtureVault()
    with tempfile.TemporaryDirectory(prefix='comic-pi-ui-') as root:
        if os.environ.get('PI_REVIEW_SNAPSHOT'):
            import shutil,sqlite3
            from pathlib import Path
            snapshot=Path(os.environ['PI_REVIEW_SNAPSHOT']).resolve()
            if not snapshot.name.startswith('comic-pi-review-copy-'):raise RuntimeError('仅接受本轮隔离验收快照')
            with sqlite3.connect(f'file:{snapshot / "workbench.sqlite"}?mode=ro',uri=True) as check:
                if not check.execute("SELECT 1 FROM projects WHERE id='pi-review' AND name='Pi 集成隔离验收'").fetchone():raise RuntimeError('验收快照不匹配')
                profiles=json.loads(check.execute('SELECT content FROM settings WHERE id=1').fetchone()[0])
                if any(not v.get('url','').startswith('http://127.0.0.1:18767/') for v in profiles.values() if isinstance(v,dict)):raise RuntimeError('快照只能使用本机替身')
            shutil.copytree(snapshot,root,dirs_exist_ok=True)
        app=module.create_app(root);store=app.state.store
        with store.db() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id='pi-review'").fetchone():
                db.execute("INSERT INTO projects VALUES('pi-review','Pi 集成隔离验收',0,'2026-11-05','2026-11-05')")
                document=import_document(store,db,'pi-review','隔离小说.txt','第一章 归来\n林秋在雨夜回到故乡，遇见多年未见的沈宁。\n第二章 来信\n沈宁交给林秋一封密信。'.encode())
                from backend import graph_store as gs
                graph=gs.empty();graph['original']['nodes']=[gs.node({'id':'fixture-person','label':'林秋','summary':'【隔离夹具】林秋雨夜归乡。'})];gs.publish(store,db,'pi-review',graph,'隔离测试图谱')
                store.add(db,'pi-review','style','隔离画风提示',{'prompt':'【隔离夹具】二维清晰线条','description':'尚未生成真实画风图'})
                store.add(db,'pi-review','asset','隔离人物提示',{'prompt':'【隔离夹具】林秋人物参考','description':'尚未生成真实人物图'})
                store.add(db,'pi-review','skeleton','改编骨架',{'text':'围绕归乡与密信组织第一单元。'})
                if os.environ.get('PI_REVIEW_SELECTION'):
                    store.add(db,'pi-review','skeleton','精确选段验收',{'html':'<h2>开头😀</h2><p>重复<strong>文字</strong>，重复文字。</p><p>保留前文A</p><p>B保留后文</p><ul><li><p>末尾列表保留</p></li></ul>'})
                store.add(db,'pi-review','outline','分集细纲',{'html':'<h3>第2话 密信</h3><p>林秋与沈宁核对密信。</p><h3>第3话 街头</h3><p>二人沿故乡街头寻找线索。</p>'})
                store.add(db,'pi-review','script','第1话第1格',{'episode':1,'panel':1,'batch':1,'description':'雨夜重逢','characters':'林秋、沈宁','scene':'故乡街头'})
                store.add(db,'pi-review','package','第1话第1格生图包',{'episode':1,'panel':1,'batch':1,'prompt':'雨夜街头，林秋与沈宁重逢。'})
                db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':'http://127.0.0.1:18767/v1','model':'ui-fixture','purpose':'text'}}),))
                if os.environ.get('PI_REVIEW_IMAGE_BATCH'):
                    for episode,panel,prompt in [(4,1,'【慢速生图验收】雨夜人物中景'),(4,2,'雨夜街头信件特写'),(4,3,'二人抬头望向故乡街口'),(5,1,'【未知生图验收】未知返回测试'),(5,2,'独立格继续生成测试')]:
                        store.add(db,'pi-review','package',f'批次验收 · 第{episode}话第{panel}格',{'episode':episode,'panel':panel,'batch':1,'prompt':prompt,'references':[]},'manual')
                if os.environ.get('PI_REVIEW_IMAGE_DEPENDENCIES'):
                    parent=store.add(db,'pi-review','package','前图依赖验收 · 第6话第1格',{'episode':6,'panel':1,'batch':1,'prompt':'【慢速生图验收】雨夜递出密信，保持手部位置','references':[]},'manual')
                    store.add(db,'pi-review','package','前图依赖验收 · 第6话第2格',{'episode':6,'panel':2,'batch':1,'prompt':'接过密信的手部特写，保持上一格空间连续性','references':[],'generation_dependencies':[{'id':parent['id'],'version':parent['version']}]},'manual')
                    store.add(db,'pi-review','package','前图依赖验收 · 第6话第3格',{'episode':6,'panel':3,'batch':1,'prompt':'独立支线，故乡街口远景','references':[]},'manual')
                if os.environ.get('PI_REVIEW_IMAGE_POSTPROCESS'):
                    for episode,panel,prompt in [(8,1,'【自动返修验收】林秋右手递出密信'),(8,2,'【慢速视觉验收】故乡街口独立支线'),(9,1,'【未知视觉验收】未知检查不得触发返修'),(9,2,'普通场景检查，问题交人工')]:
                        store.add(db,'pi-review','package',f'检查返修验收 · 第{episode}话第{panel}格',{'episode':episode,'panel':panel,'batch':1,'prompt':prompt,'references':[]},'manual')
                if os.environ.get('PI_REVIEW_IMAGES'):
                    row=json.loads(db.execute('SELECT content FROM settings WHERE id=1').fetchone()[0]);row['image']={'purpose':'image','url':'http://127.0.0.1:18767/v1','model':'gpt-image-1.5','api':'openai-images'};db.execute('UPDATE settings SET content=? WHERE id=1',(json.dumps(row),))
                if os.environ.get('PI_REVIEW_VISION'):
                    from backend.simulation import demo_image
                    from backend.store import uid,now
                    row=json.loads(db.execute('SELECT content FROM settings WHERE id=1').fetchone()[0]);row['vision']={'purpose':'vision','url':'http://127.0.0.1:18767/v1','model':'ui-vision-fixture','api':'openai-completions'};db.execute('UPDATE settings SET content=? WHERE id=1',(json.dumps(row),))
                    image_url=store.file(db,'pi-review','视觉验收合成图.png',demo_image(0),'image/png')
                    for kind,title in [('image','第1话第1格视觉验收'),('style','视觉参考画风'),('asset','视觉参考人物')]:
                        r=store.add(db,'pi-review',kind,title,{'episode':1,'panel':1,'batch':1,'url':image_url,'width':640,'height':900,'prompt':'【隔离视觉】雨中重逢'},'mock')
                        if kind!='image':db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],1,'approved','隔离参考',r['source'],now()))
                if os.environ.get('PI_REVIEW_SCRIPT_CRUD'):
                    import base64
                    image_url=store.file(db,'pi-review','隔离底图.png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII='),'image/png')
                    image=store.add(db,'pi-review','image','第1话第1格隔离图片',{'episode':1,'panel':1,'batch':1,'url':image_url,'width':1,'height':1})
                    store.add(db,'pi-review','trial','首话试制确认',{'references':[{'id':image['id'],'version':1}]})
                if os.environ.get('PI_REVIEW_DOCUMENTS'):
                    db.execute("INSERT INTO projects VALUES('pi-doc-empty','文档首次生成隔离验收',0,'2026-11-05','2026-11-05')")
                    first=import_document(store,db,'pi-doc-empty','首次验收原著.txt','第一章 归来\n人物归乡后收到一封密信。'.encode())
                    app.state.graph_engine.create_job(db,'pi-doc-empty',did=first['id'])
                if os.environ.get('PI_REVIEW_GRAPH_USAGE'):
                    job=app.state.graph_engine.create_job(db,'pi-review',did=document['id'])
                    db.execute("UPDATE graph_jobs SET status='succeeded',stage='publish',completed=total,usage=? WHERE id=?",(json.dumps({'input_tokens':12,'output_tokens':8,'unknown':True}),job['id']))
        if os.environ.get('PI_REVIEW_STYLE_TESTS'):
            from backend.store import uid,now
            with store.db() as db:
                row=db.execute("SELECT id,version FROM records WHERE project_id='pi-review' AND kind='outline' ORDER BY created LIMIT 1").fetchone()
                if row and not db.execute("SELECT 1 FROM reviews WHERE record_id=? AND version=? AND decision='approved'",(row['id'],row['version'])).fetchone():
                    db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),row['id'],row['version'],'approved','仅隔离三套画风审核夹具','manual',now()))
        if os.environ.get('PI_REVIEW_SETUP_CATALOG'):
            from backend.skills import install
            for i in range(55):
                install(store,{'format':'comic-skill/v1','id':f'ui-catalog-{i}','name':f'隔离目录流程{i}','version':'1','stages':['setup'],'tags':['一致性'],'entrypoint':'SKILL.md','files':{'SKILL.md':'只核对配置用途，操作仍需明确采用。'}})
        if os.environ.get('PI_REVIEW_VISION_GROUNDING'):
            from backend.skills import install
            skill=install(store,{'format':'comic-skill/v1','id':'ui-vision-rules','name':'隔离视觉审核流程','version':'1','stages':['review'],'entrypoint':'SKILL.md','files':{'SKILL.md':'先核对人物服饰与所选原著。参照[证据规范](references/evidence.md)。','references/evidence.md':'只引用实际提供的原著片段，说明未读范围。'}})
            with store.db() as db:
                if not db.execute('SELECT 1 FROM project_skill_settings WHERE project_id=?',('pi-review',)).fetchone():db.execute('INSERT INTO project_skill_settings VALUES(?,?,?)',('pi-review',1,json.dumps([skill['hash']])))
        if os.environ.get('PI_REVIEW_BATCH_CONTROL'):
            from pydantic import BaseModel,ConfigDict,Field
            class AdvanceClock(BaseModel):
                model_config=ConfigDict(extra='forbid',strict=True)
                seconds:int=Field(gt=0,le=25201)
            offset=[0.];app.state.image_batch_control.now=lambda:time.monotonic()+offset[0]
            @app.post('/api/review/clock-advance')
            def advance_clock(body:AdvanceClock):
                offset[0]+=body.seconds
                return {'fixture_only':True,'injected_seconds':offset[0],'note':'仅临时隔离时钟注入，不代表真实经过7小时'}
            # create_app already mounted the root SPA; fixture-only API must precede it.
            app.router.routes.insert(0,app.router.routes.pop())
        if os.environ.get('PI_REVIEW_RETRY'):
            # Synthetic pre-connect failure: no provider request is sent on the first attempt.
            import httpx
            forward=httpx.AsyncHTTPTransport()
            seen_image_calls=set()
            async def retry_fixture_transport(request):
                aid=request.headers.get('X-Client-Request-Id')
                with store.db() as db:
                    row=db.execute('SELECT call_id FROM image_attempts WHERE id=?',(aid,)).fetchone() if aid else None
                if row and row['call_id'] not in seen_image_calls:
                    seen_image_calls.add(row['call_id'])
                    raise httpx.ConnectError('synthetic pre-connect failure',request=request)
                return await forward.handle_async_request(request)
            app.state.image_provider.transport=httpx.MockTransport(retry_fixture_transport)
            app.router.on_shutdown.append(forward.aclose)
        if os.environ.get('PI_REVIEW_RECOVERY'):
            # QA-only real lost acknowledgement: result commits, then the private runtime exits.
            original_tool=app.state.pi_runtime._tool
            dropped=set()
            async def drop_recovery_ack(message,on_tool):
                rid=message.get('run_id');marked=False;pending_pause=False
                with store.db() as db:
                    discussion=db.execute("SELECT message FROM agent_runs WHERE id=? AND project_id='pi-review'",(rid,)).fetchone()
                    production=db.execute("SELECT t.payload FROM tasks t JOIN production_attempts a ON a.task_id=t.id WHERE a.id=? AND t.project_id='pi-review'",(rid,)).fetchone()
                    pending_pause=bool(discussion and '【未决暂停验收】' in discussion[0])
                    marked=bool(discussion and '【工具恢复验收】' in discussion[0] or production and '【工具恢复验收】' in json.loads(production[0]).get('instruction',''))
                    if db.execute('SELECT 1 FROM agent_continuations WHERE child_run_id=? UNION ALL SELECT 1 FROM production_continuations WHERE child_id=?',(rid,rid)).fetchone():marked=False
                if pending_pause:
                    import asyncio
                    await asyncio.sleep(1)
                if marked and rid not in dropped:
                    await on_tool(message)
                    dropped.add(rid)
                    app.state.pi_runtime.process.kill()
                else:await original_tool(message,on_tool)
            app.state.pi_runtime._tool=drop_recovery_ack
            @app.post('/api/review/runtime-restart')
            async def restart_recovery_runtime():
                runtime=app.state.pi_runtime
                if runtime.process and runtime.process.returncode is None and runtime.status!='ready':
                    return {'fixture_only':True,'status':'waiting_for_exit'}
                await runtime.start()
                return {'fixture_only':True,'status':runtime.status,'dropped_runs':len(dropped)}
            app.router.routes.insert(0,app.router.routes.pop())
        if os.environ.get('PI_REVIEW_SELECTION'):
            @app.middleware('http')
            async def delayed_selection_apply(request,call_next):
                if request.url.path.endswith('/apply-selection'):
                    import asyncio
                    await asyncio.sleep(3)
                return await call_next(request)
        print('隔离验收地址 http://127.0.0.1:18766；临时数据退出删除；仅本机替身，无真实付费调用',flush=True)
        try: uvicorn.run(app,host='127.0.0.1',port=18766,access_log=False)
        finally: provider.shutdown();provider.server_close()
