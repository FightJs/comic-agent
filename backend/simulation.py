"""Deterministic, explicitly labelled demo outputs. No provider/network calls."""
import html
import io
from PIL import Image, ImageDraw


def demo_image(index=0):
    image=Image.new('RGB',(640,900),(235,237,226))
    draw=ImageDraw.Draw(image)
    draw.rectangle((32,32,608,868),outline=(88,98,66),width=3)
    draw.rectangle((70,180,570,650),fill=(205,213,190))
    draw.ellipse((230,240,410,420),fill=(117,131,96))
    draw.polygon([(320,395),(170,650),(470,650)],fill=(117,131,96))
    draw.text((70,90),'SIMULATION / NOT AI GENERATED',fill=(40,50,30),font_size=24)
    draw.text((70,720),f'PANEL {index+1:03d}  -  REVIEW FIXTURE',fill=(40,50,30),font_size=22)
    draw.text((70,765),'Import your artwork to review real images.',fill=(40,50,30),font_size=18)
    out=io.BytesIO(); image.save(out,'PNG'); return out.getvalue()


def content_for(kind, old, request):
    if kind == 'memory':
        return {'notice':'此关系图为预置流程样例，并非当前小说提取结果。','nodes':[
            {'id':'qing','label':'阿青','type':'人物','description':'示例主角','source':'预置演示，不对应原文'},
            {'id':'lin','label':'林先生','type':'人物','description':'示例导师','source':'预置演示，不对应原文'},
            {'id':'yard','label':'旧院','type':'场景','description':'示例相遇地点','source':'预置演示，不对应原文'}],
            'edges':[{'source':'qing','target':'lin','label':'师徒 · 示例'},{'source':'qing','target':'yard','label':'到访 · 示例'}]}
    if kind in ('skeleton','outline'):
        title='全书改编骨架' if kind=='skeleton' else '分集细纲'
        return {'html':f'<h2>{title} · 模拟样例</h2><p>以下内容用于验证编辑与审核流程，不是对导入小说的真实改编。</p><h3>第一话 · 重返旧院</h3><p>阿青回到旧院，在树下找到一封未寄出的信。人物在选择与疑问中推进情节。</p><h3>第二话 · 未说完的话</h3><p>她决定寻找写信的人。请替换为你的正式内容，模拟来源将继续保留。</p>'}
    if kind=='script':
        return {**old,'characters':'阿青','scene':'旧院','weather':'晴','time':'黄昏','shot':'中景','camera':'平视','description':'【模拟】阿青停在旧院门前，望向院中老树。此为预置演示。','dialogue':'这里还和从前一样。','sfx':'','note':'非当前小说真实改编'}
    if kind=='package':
        return {**old,'camera':'平视 / 中景','prompt':'【模拟生图包】二维漫画。阿青站在旧院门口，黄昏侧光，视线朝向院中老树。此为演示提示词，不会调用模型。','references':old.get('references',[]),'parameters':'模型未接入；参数未验证','dependencies':'无真实前图依赖','missing':'需正式脚本、审核资产和真实模型适配'}
    return {**old,'html':f'<p>【模拟结果】{html.escape(request.get("instruction", "流程演示"))}</p>'}
