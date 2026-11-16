import { useEffect, useState } from 'react'
import { BookOpen, Clapperboard, Layers3, PenLine, Palette, Package, Images, Network, FileText, ChevronRight } from 'lucide-react'
import './pages-demo.css'

const stages = [
  { id: 'original', label: '理解与记忆', icon: BookOpen },
  { id: 'skeleton', label: '改编与细纲', icon: PenLine },
  { id: 'style', label: '画风与资产', icon: Palette },
  { id: 'script', label: '脚本审核', icon: Clapperboard },
  { id: 'package', label: '逐格生图包', icon: Package },
  { id: 'images', label: '图片工作区', icon: Images },
] as const
type Stage = typeof stages[number]['id']
const readStage = (): Stage => stages.find(x => x.id === location.hash.slice(1))?.id ?? 'original'

export default function PagesDemo() {
  const [stage, setStage] = useState<Stage>(readStage)
  useEffect(() => { const update = () => setStage(readStage()); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  const current = stages.find(x => x.id === stage)!
  const production = ['script', 'package', 'images'].includes(stage)
  const navigate = (id: Stage) => { location.hash = id; setStage(id) }
  return <div className="demo-app">
    <aside className="demo-sidebar">
      <div className="demo-brand"><span><Layers3 size={20}/></span><strong>条漫 Agent</strong></div>
      <div className="demo-project"><small>正在创作 · 示例项目</small><strong>星港来信</strong></div>
      <div className="demo-nav-title">全书前期准备</div>
      <nav aria-label="工作阶段">{stages.map((item, i) => <div key={item.id}>{i === 3 && <div className="demo-nav-title production-title">批次制作</div>}<button className={stage === item.id ? 'active' : ''} aria-label={item.label} title={item.label} aria-current={stage === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><item.icon size={17}/><span>{item.label}</span></button></div>)}</nav>
      <div className="demo-side-note">前端演示<small>示例内容不保存，也不会发送到服务器</small></div>
    </aside>
    <div className="demo-main">
      <header className="demo-top"><span>星港来信 <ChevronRight size={14}/> {production ? '批次制作' : '全书前期准备'} <ChevronRight size={14}/> <strong>{current.label}</strong></span><a href="https://github.com/FightJs/comic-agent">查看项目源码 ↗</a></header>
      <div className="demo-notice" role="status">前端演示 · 页面均为合成示例，未连接后端；导入、编辑保存、AI 调用与图像生成不可用。</div>
      <main className="demo-content">
        <div className="demo-heading"><div><h1>{current.label}</h1><p>{production ? '第 1–10 话制作 · 第 1 话' : '全书前期准备 · 示例项目'}</p></div><span className="demo-tag">只读示例</span></div>
        {stage === 'original' && <><div className="demo-tabs"><span className="selected">原著阅读</span></div><div className="demo-reading"><section className="demo-outline"><h2>原著目录</h2><div className="demo-selected"><FileText size={15}/> 第一章 · 灯塔的信</div></section><article className="demo-paper"><div className="demo-eyebrow">合成原著示例 · 第一章</div><h2>灯塔的信</h2><p>傍晚，阿遥在旧灯塔的台阶上发现一封没有署名的信。信纸被海风吹得发软，折痕里夹着一枚蓝色的车票。</p><p>“如果你看见这封信，请在涨潮前到北岸。”她抬头望向远处，港口的灯一盏接一盏亮起来。</p><p>阿遥收好车票，沿着石阶向海边跑去。她不知道，这封信将带她重新认识这座小城。</p><div className="demo-footnote">此段文字专为界面演示编写，并非真实原著。</div></article></div></>}
        {stage === 'skeleton' && <><div className="demo-tabs"><span className="selected">全书骨架</span></div><section className="demo-document"><div className="demo-toolbar"><strong>全书骨架 · 示例</strong><span>只读</span></div><h2>故事概要</h2><p>阿遥追寻一封无署名的信，在寻找寄信人的过程中重新认识家乡与自己。</p><h3>主要推进</h3><ol><li><strong>引子：</strong>灯塔发现信件，前往北岸。</li><li><strong>发展：</strong>旧车票引出一段尘封的港口记忆。</li><li><strong>收束：</strong>阿遥找到写信的人，并决定留下记录。</li></ol></section></>}
        {stage === 'style' && <><div className="demo-tabs"><span className="selected">画风方案</span></div><section className="demo-document"><div className="demo-toolbar"><strong>画风设定 · 示例</strong><span>只读</span></div><h2>安静的海港日常</h2><p>柔和自然光、克制的暖灰色调，画面以人物情绪与空间叙事为主。</p><h3>角色与场景</h3><div className="demo-asset-list"><div><Palette size={18}/><strong>阿遥</strong><span>角色设定 · 示例文字</span></div><div><Network size={18}/><strong>旧灯塔</strong><span>场景设定 · 示例文字</span></div></div><p className="demo-muted">展示使用文字占位，未包含真实作品或生成图片。</p></section></>}
        {stage === 'script' && <><div className="demo-toolbar"><strong>第 1 话 · 灯塔的信</strong><span>合成脚本 · 只读</span></div><p className="demo-scroll-hint">表格可左右滑动，查看完整内容。</p><div className="demo-table-wrap"><table><thead><tr><th>话 / 格</th><th>景别与画面</th><th>人物动作</th><th>对白 / 旁白</th><th>审核状态</th></tr></thead><tbody><tr><td>1 / 1</td><td>远景 · 傍晚海港与旧灯塔</td><td>阿遥走上台阶</td><td>旁白：港口的灯渐渐亮了。</td><td>示例 · 待审核</td></tr><tr><td>1 / 2</td><td>特写 · 一封信压在石阶上</td><td>阿遥弯腰拾起信</td><td>阿遥：这是谁留下的？</td><td>示例 · 待审核</td></tr><tr><td>1 / 3</td><td>中景 · 阿遥望向北岸</td><td>她握紧蓝色车票</td><td>旁白：涨潮之前，她必须找到答案。</td><td>示例 · 待审核</td></tr></tbody></table></div></>}
        {stage === 'package' && <><div className="demo-toolbar"><strong>第 1 话 · 逐格生图包</strong><span>示例内容 · 不可生成</span></div><p className="demo-scroll-hint">表格可左右滑动，查看完整内容。</p><div className="demo-table-wrap"><table><thead><tr><th>话 / 格</th><th>镜头</th><th>画面描述</th><th>参考资产</th><th>提示词摘要</th></tr></thead><tbody><tr><td>1 / 1</td><td>远景</td><td>傍晚海港与旧灯塔</td><td>旧灯塔</td><td>安静海港，柔和暮色，人物背影</td></tr><tr><td>1 / 2</td><td>特写</td><td>石阶上的信与蓝色车票</td><td>信、车票</td><td>纸张纹理，暖色侧光，近景</td></tr></tbody></table></div></>}
        {stage === 'images' && <div className="demo-image-workspace"><section className="demo-image-list"><h2>本话分镜</h2><div className="demo-image-selected">第 1 格 <small>示例占位</small></div></section><section className="demo-canvas"><div><Images size={30}/><strong>图片工作区</strong><span>演示未提供图片；真实项目可在此查看候选与批注。</span></div></section><section className="demo-comments"><h2>批注与讨论</h2><p>演示未连接图像或 AI 服务。</p><p>真实工作流中的生成、批注与采用需要在本机操作。</p></section></div>}
      </main><footer className="demo-footer">公开演示 <span>·</span> 示例数据 <span>·</span> 无后端连接</footer>
    </div>
  </div>
}
