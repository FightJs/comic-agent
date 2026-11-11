import { useEffect, useMemo, useRef, useState } from 'react';
import { quadtree, type Quadtree } from 'd3-quadtree';
import { Minus, Plus, Maximize2, LocateFixed } from 'lucide-react';
import { edgeGeometry } from './graphModel';
import type { GraphNode, GraphEdge } from './graphTypes';
type Point={id:string;x:number;y:number};
type View={x:number;y:number;k:number};
const colors:Record<string,string>={PERSON:'#637344',LOCATION:'#688681',ORGANIZATION:'#9a7853',OBJECT:'#8b7596',OTHER:'#798084',STATE:'#8d875b'};
export function GraphCanvas({nodes,edges,selected,selectedEdge,onNode,onEdge,layout,pinned,resetKey=0,filtered=false}:{nodes:GraphNode[];edges:GraphEdge[];selected:string|null;selectedEdge:string|null;onNode:(id:string|null)=>void;onEdge:(id:string)=>void;layout:'force'|'types';pinned:string[];resetKey?:number;filtered?:boolean}){
 const host=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null),positions=useRef(new Map<string,Point>()),tree=useRef<Quadtree<Point>|null>(null),view=useRef<View>({x:0,y:0,k:1}),size=useRef({w:800,h:500}),frame=useRef(0),initialFit=useRef(true),drag=useRef<{x:number;y:number;node:string|null;moved:boolean}|null>(null),localPinned=useRef(new Set<string>()),keyboardPan=useRef(false),previousPinned=useRef<string[]>([]);
 const [progress,setProgress]=useState(100),[elapsed,setElapsed]=useState(0),[zoom,setZoom]=useState(100);
 const pinSignature=pinned.join("|");
 const topology=useMemo(()=>nodes.map(n=>n.id+':'+n.type).join('|')+'#'+edges.map(e=>e.id+':'+e.source+':'+e.target).join('|'),[nodes,edges]);
 const live=useRef({nodes,edges,selected,selectedEdge,onNode,onEdge});live.current={nodes,edges,selected,selectedEdge,onNode,onEdge};
 const pairInfo=useRef(new Map<string,{i:number;n:number}>());
 const drawRef=useRef<()=>void>(()=>{});
 function schedule(){cancelAnimationFrame(frame.current);frame.current=requestAnimationFrame(()=>drawRef.current());}
 function rebuildTree(){tree.current=quadtree<Point>().x(n=>n.x).y(n=>n.y).addAll([...positions.current.values()]);}
 function fit(){const pts=live.current.nodes.map(n=>positions.current.get(n.id)).filter(Boolean) as Point[];if(!pts.length)return;let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;for(const p of pts){minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y);}const {w,h}=size.current;const k=Math.min(1,(w-90)/(maxX-minX+170),(h-90)/(maxY-minY+110));view.current={x:w/2-(minX+maxX)/2*k,y:h/2-(minY+maxY)/2*k,k:Math.max(.015,k)};setZoom(Math.round(k*100));schedule();}
 function zoomBy(factor:number,x=size.current.w/2,y=size.current.h/2){const v=view.current,k=Math.max(.012,Math.min(2.5,v.k*factor));view.current={x:x-(x-v.x)*k/v.k,y:y-(y-v.y)*k/v.k,k};setZoom(Math.round(k*100));schedule();}
 drawRef.current=()=>{
  const ctx=canvas.current?.getContext('2d');if(!ctx)return;const {w,h}=size.current,dpr=window.devicePixelRatio||1,v=view.current,g=live.current;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#f5f6f0';ctx.fillRect(0,0,w,h);
  ctx.fillStyle='#daddd0';const step=32*v.k;if(step>10){for(let x=((v.x%step)+step)%step;x<w;x+=step)for(let y=((v.y%step)+step)%step;y<h;y+=step)ctx.fillRect(x,y,1,1);}
  ctx.translate(v.x,v.y);ctx.scale(v.k,v.k);
  const bounds={l:-v.x/v.k-150,r:(w-v.x)/v.k+150,t:-v.y/v.k-100,b:(h-v.y)/v.k+100};
  const outside=(p:Point)=>p.x<bounds.l||p.x>bounds.r||p.y<bounds.t||p.y>bounds.b;
  for(const e of g.edges){const s=positions.current.get(e.source),t=positions.current.get(e.target);if(!s||!t)continue;if((s.x<bounds.l&&t.x<bounds.l)||(s.x>bounds.r&&t.x>bounds.r)||(s.y<bounds.t&&t.y<bounds.t)||(s.y>bounds.b&&t.y>bounds.b))continue;
   const focused=e.id===g.selectedEdge||e.source===g.selected||e.target===g.selected;
   const pair=pairInfo.current.get(e.id)||{i:0,n:1},c=edgeGeometry(s.x,s.y,t.x,t.y,pair.i,pair.n);
   ctx.strokeStyle=focused?'#465c2e':g.selected?'#cbd0c0':'#a4ae95';ctx.lineWidth=(focused?2:1)/Math.max(v.k,.4);ctx.setLineDash(e.inferred?[6/Math.max(v.k,.4),4/Math.max(v.k,.4)]:[]);
   ctx.beginPath();ctx.moveTo(s.x,s.y);if(s.id===t.id){ctx.bezierCurveTo(s.x-100,s.y-110,s.x+100,s.y-110,s.x,s.y);}else ctx.quadraticCurveTo(c.cx,c.cy,t.x,t.y);ctx.stroke();ctx.setLineDash([]);
   if(v.k>.22||focused){const tt=.72,xx=(1-tt)**2*s.x+2*(1-tt)*tt*c.cx+tt*tt*t.x,yy=(1-tt)**2*s.y+2*(1-tt)*tt*c.cy+tt*tt*t.y,angle=Math.atan2(t.y-c.cy,t.x-c.cx);ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(xx,yy);ctx.lineTo(xx-9*Math.cos(angle-.45),yy-9*Math.sin(angle-.45));ctx.lineTo(xx-9*Math.cos(angle+.45),yy-9*Math.sin(angle+.45));ctx.closePath();ctx.fill();}
   if(v.k>.6&&(g.edges.length<400||focused)){const mx=.25*s.x+.5*c.cx+.25*t.x,my=.25*s.y+.5*c.cy+.25*t.y;ctx.font='12px -apple-system, sans-serif';ctx.textAlign='center';const label=e.relation+(e.inferred?' · 推断':'');const tw=ctx.measureText(label).width;ctx.fillStyle='#f5f6f0';ctx.fillRect(mx-tw/2-4,my-9,tw+8,18);ctx.fillStyle=focused?'#344426':'#58634d';ctx.fillText(label,mx,my+4);}
  }
  for(const n of g.nodes){const p=positions.current.get(n.id);if(!p||outside(p))continue;const chosen=n.id===g.selected;ctx.fillStyle=chosen?'#e8eedb':'#fff';ctx.strokeStyle=chosen?'#526a35':colors[n.type]||colors.OTHER;ctx.lineWidth=chosen?2.5:1.2;
   if(v.k<.25){ctx.fillStyle=chosen?'#334b1d':colors[n.type]||colors.OTHER;ctx.beginPath();ctx.arc(p.x,p.y,chosen?14:8,0,Math.PI*2);ctx.fill();continue;}
   ctx.beginPath();ctx.roundRect(p.x-65,p.y-26,130,52,6);ctx.fill();ctx.stroke();ctx.fillStyle=colors[n.type]||colors.OTHER;ctx.fillRect(p.x-65,p.y-18,3,36);
   ctx.textAlign='center';ctx.font='500 13px -apple-system, sans-serif';ctx.fillStyle='#30372c';const label=n.label.length>9?n.label.slice(0,8)+'…':n.label;ctx.fillText((n.important?'★ ':'')+label,p.x,p.y+2);
   if(v.k>.5){ctx.font='10px -apple-system, sans-serif';ctx.fillStyle='#656e5d';const sub=n.type==='STATE'?'状态':({PERSON:'人物',LOCATION:'场景',ORGANIZATION:'组织',OBJECT:'道具',OTHER:'其他'} as Record<string,string>)[n.type]||n.type;ctx.fillText(sub,p.x,p.y+17);}
  }
 };
 useEffect(()=>{const pairs=new Map<string,string[]>();for(const e of edges){const key=[e.source,e.target].sort().join('|');const p=pairs.get(key)||[];p.push(e.id);pairs.set(key,p);}pairInfo.current.clear();for(const arr of pairs.values())arr.forEach((id,i)=>pairInfo.current.set(id,{i,n:arr.length}));schedule();},[nodes,edges,selected,selectedEdge]);
 useEffect(()=>{const el=host.current;if(!el)return;const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;size.current={w:r.width,h:r.height};if(canvas.current){canvas.current.width=r.width*(devicePixelRatio||1);canvas.current.height=r.height*(devicePixelRatio||1);}schedule();});observer.observe(el);return()=>{observer.disconnect();cancelAnimationFrame(frame.current);};},[]);
 useEffect(()=>{positions.current.clear();localPinned.current.clear();initialFit.current=true;},[resetKey]);
 useEffect(()=>{if(!selected)return;const p=positions.current.get(selected);if(!p)return;const v=view.current,{w,h}=size.current;const x=p.x*v.k+v.x,y=p.y*v.k+v.y;if(x<80||x>w-80||y<60||y>h-60){view.current={...v,x:w/2-p.x*v.k,y:h/2-p.y*v.k};schedule();}},[selected]);
 useEffect(()=>{for(const id of previousPinned.current)if(!pinned.includes(id))localPinned.current.delete(id);for(const id of pinned)localPinned.current.add(id);previousPinned.current=pinned;},[pinSignature]);
 useEffect(()=>{
  if(!nodes.length)return;const start=performance.now();setProgress(0);const ids=new Set(nodes.map(n=>n.id));for(const id of positions.current.keys())if(!ids.has(id))positions.current.delete(id);
  nodes.forEach((n,i)=>{if(!positions.current.has(n.id)){const a=i*2.39996,r=Math.sqrt(i)*110;positions.current.set(n.id,{id:n.id,x:Math.cos(a)*r,y:Math.sin(a)*r});}});rebuildTree();if(initialFit.current)fit();
  const worker=new Worker(new URL('./graphLayout.worker.ts',import.meta.url),{type:'module'});
  worker.onmessage=e=>{for(const p of e.data.positions as Point[])if(!localPinned.current.has(p.id)&&drag.current?.node!==p.id)positions.current.set(p.id,p);setProgress(e.data.progress);setElapsed(e.data.elapsed);rebuildTree();if(initialFit.current&&(e.data.progress===100||performance.now()-start>800)){fit();if(e.data.progress===100)initialFit.current=false;}else schedule();};
  worker.postMessage({nodes:nodes.map(n=>({...positions.current.get(n.id),type:n.type,...(pinned.includes(n.id)?{fx:positions.current.get(n.id)?.x,fy:positions.current.get(n.id)?.y}:{})})),edges:edges.map(e=>({source:e.source,target:e.target})),mode:layout});return()=>worker.terminate();
 },[topology,layout,resetKey,pinSignature]);
 useEffect(()=>{const el=canvas.current;if(!el)return;const wheel=(e:WheelEvent)=>{e.preventDefault();const r=el.getBoundingClientRect();if(e.ctrlKey||e.metaKey)zoomBy(Math.exp(-e.deltaY*.006),e.clientX-r.left,e.clientY-r.top);else{view.current.x-=e.deltaX;view.current.y-=e.deltaY;schedule();}};el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);},[]);
 function world(x:number,y:number){const r=canvas.current!.getBoundingClientRect(),v=view.current;return{x:(x-r.left-v.x)/v.k,y:(y-r.top-v.y)/v.k};}
 function hit(x:number,y:number){const p=tree.current?.find(x,y,75);return p&&Math.abs(x-p.x)<70&&Math.abs(y-p.y)<30?p:null;}
 function edgeHit(x:number,y:number){let best:string|null=null,dist=10/view.current.k;for(const e of edges){const s=positions.current.get(e.source),t=positions.current.get(e.target);if(!s||!t)continue;const pi=pairInfo.current.get(e.id)||{i:0,n:1};const c=edgeGeometry(s.x,s.y,t.x,t.y,pi.i,pi.n);for(let j=1;j<16;j++){const f=j/16;const d=Math.hypot(x-((1-f)**2*s.x+2*(1-f)*f*c.cx+f*f*t.x),y-((1-f)**2*s.y+2*(1-f)*f*c.cy+f*f*t.y));if(d<dist){best=e.id;dist=d;}}}return best;}
 return <div className="graph-canvas-host" ref={host}>
  <canvas ref={canvas} tabIndex={0} aria-label="知识图谱画布。方向键平移，加减键缩放；通过节点和关系列表进行键盘选择与编辑。" onKeyDown={e=>{if(e.key===' '){e.preventDefault();keyboardPan.current=true;}if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();view.current.x+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;view.current.y+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0;schedule();}if(e.key==='+'||e.key==='=')zoomBy(1.2);if(e.key==='-')zoomBy(1/1.2);if(e.key==='0')fit();}} onKeyUp={e=>{if(e.key===' ')keyboardPan.current=false;}} onBlur={()=>keyboardPan.current=false}
   onPointerDown={e=>{if(e.button!==0&&e.button!==1)return;e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);const p=world(e.clientX,e.clientY);drag.current={x:e.clientX,y:e.clientY,node:keyboardPan.current||e.button===1?null:hit(p.x,p.y)?.id||null,moved:false};}}
   onPointerMove={e=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>2)d.moved=true;if(d.node){const p=positions.current.get(d.node);if(p){p.x+=dx/view.current.k;p.y+=dy/view.current.k;localPinned.current.add(d.node);}}else{view.current.x+=dx;view.current.y+=dy;}d.x=e.clientX;d.y=e.clientY;schedule();}}
   onPointerUp={e=>{const d=drag.current;drag.current=null;rebuildTree();if(d&&!d.moved){const p=world(e.clientX,e.clientY);if(d.node)onNode(d.node);else{const id=edgeHit(p.x,p.y);if(id)onEdge(id);else onNode(null);}}}} onPointerCancel={()=>drag.current=null}/>
  <div className="graph-canvas-tools"><button title="放大" aria-label="放大图谱" onClick={()=>zoomBy(1.25)}><Plus size={15}/></button><span>{zoom}%</span><button title="缩小" aria-label="缩小图谱" onClick={()=>zoomBy(.8)}><Minus size={15}/></button><button title="适应画布" aria-label="适应画布" onClick={fit}><Maximize2 size={15}/></button><button title="定位选中节点" aria-label="定位选中节点" disabled={!selected} onClick={()=>{const p=positions.current.get(selected!);if(p){view.current={x:size.current.w/2-p.x,y:size.current.h/2-p.y,k:1};setZoom(100);schedule();}}}><LocateFixed size={15}/></button></div>
  <div className="graph-canvas-caption" role="status">{progress<100?`后台布局 ${progress}%`:`${nodes.length} 个节点 · ${edges.length} 条关系`}{elapsed>0&&progress===100&&<span>布局 {(elapsed/1000).toFixed(1)}s</span>}</div>
  {!nodes.length&&<div className="graph-canvas-empty"><strong>{filtered?'当前条件下暂无可见实体':'这里将呈现人物与世界的关联'}</strong><p>{filtered?'请调整实体类型、关系或披露进度，或切回全书查看。':'导入原著完成成图，或新建一个人物开始整理。'}</p></div>}
 </div>;
}
