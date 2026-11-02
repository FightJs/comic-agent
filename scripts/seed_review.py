"""Create clearly labelled QA fixtures in the isolated review service, never 8765."""
import io
import httpx
from PIL import Image,ImageDraw

URL='http://127.0.0.1:8766/api'
with httpx.Client(base_url=URL,timeout=30) as c:
    def post(path,**kwargs):
        r=c.post(path,**kwargs);r.raise_for_status();return r.json()
    p=post('/projects',json={'name':'审查专用 · 百格长篇工作流与长名称边界验证项目（非业务数据）'})['id']
    prefix=f'/projects/{p}'
    def record(kind,title,content,source='manual'):
        return post(prefix+'/records',json={'kind':kind,'title':title,'content':content,'source':source})
    novel='审查专用前言。以下均为流程测试样例。\n'+''.join(f'第{i}章 来信\n'+('阿青回到旧院，寻找来信的主人。林先生在树下等待。\n'*15) for i in range(1,21))
    post(prefix+'/text',files={'file':('带前言的长原著.txt',novel.encode(),'text/plain')})
    post(prefix+'/text',files={'file':('无章节原文.txt','审查样例，没有章节标题。阿青第一次读信。第二次读信。'.encode('gb18030'),'text/plain')})
    for kind in ['skeleton','outline']:
        html=''.join(f'<h2>第{i}话 · 审查段落</h2><p>'+('阿青望向旧院，来信使她重新思考去留。'*12)+'</p>' for i in range(1,31))
        record(kind,'长文审查 · '+kind,{'html':html})
    scripts=[]
    for panel in range(1,101):
        scripts.append(record('script',f'第1话 第{panel}格',{'batch':1,'episode':1,'panel':panel,'characters':'阿青' if panel%2 else '林先生','scene':'旧院' if panel%3 else '山林','weather':'晴','time':'黄昏','shot':'中景','camera':'平视','description':f'第{panel}格定位验收。'+('人物停在门前，动作与视线具有明确依据。'*12),'dialogue':'这封信是谁写的？','sfx':'','note':'审查专用，不是正式创作内容'}))
    scripts.append(record('script','第2话 第1格',{'batch':1,'episode':2,'panel':1,'characters':'阿青','scene':'山林','description':'第二话上下文连续性验收'}))
    def artwork(label,color):
        im=Image.new('RGB',(640,900),color);d=ImageDraw.Draw(im);d.text((40,50),'UI REVIEW FIXTURE',fill='#202820',font_size=34);d.text((40,130),label,fill='#202820',font_size=24);out=io.BytesIO();im.save(out,'PNG');return out.getvalue()
    styles=[]
    for i,color in enumerate(['#dce6bf','#c8dbe5','#ead2ce']):
        styles.append(post(prefix+'/images',data={'kind':'style'},files={'file':(f'画风方案{i+1}.png',artwork('STYLE '+str(i+1),color),'image/png')}))
    post(prefix+f'/records/{styles[0]["id"]}/reviews',json={'version':1,'decision':'approved','note':'审查采用候选A'})
    post(prefix+'/style-selection',json={'record_id':styles[0]['id'],'version':1})
    asset=post(prefix+'/images',data={'kind':'asset','category':'人物'},files={'file':('阿青长名称人物资产_正面衣装状态与配饰参考_审查专用.png',artwork('ASSET V1','#d6dec8'),'image/png')})
    for episode,script in [(1,scripts[0]),(2,scripts[-1])]:
        record('package',f'第{episode}话 第1格生图包',{'batch':1,'episode':episode,'panel':1,'script_id':script['id'],'script_version':1,'references':[{'id':asset['id'],'version':1,'purpose':'身份与衣装参考'}],'camera':'平视中景','prompt':'完整提示词审查。'+('人物站在旧院门前，保持衣装与身份，参考图不决定姿态。'*30),'parameters':'模型未接入','dependencies':'无前图依赖','missing':'仅用于界面审查'})
        image=post(prefix+'/images',data={'kind':'image','batch':1,'episode':episode,'panel':1},files={'file':(f'E{episode}-P001-v1.png',artwork(f'EPISODE {episode} / V1','#d2dfc4'),'image/png')})
        post(prefix+'/images',data={'kind':'image','record_id':image['id'],'expected_version':1},files={'file':(f'E{episode}-P001-v2.png',artwork(f'EPISODE {episode} / V2','#ccdbe5'),'image/png')})
    post(prefix+'/images',data={'kind':'asset','record_id':asset['id'],'expected_version':1},files={'file':('阿青资产-v2.png',artwork('ASSET V2','#e4d2ca'),'image/png')})
    post(prefix+'/tasks',json={'kind':'memory'})
    post(prefix+'/tasks',json={'kind':'outline','fail':True})
    print('Review project:',p)
    print('Ready: 101 scripts, 2 novels, 2 long documents, 3 styles, 1 asset with 2 versions, 2 packages and 2 images with 2 versions.')
