import type { Graph, GraphNode, GraphEdge, Operation } from './graphTypes';
export type ViewMode='overview'|'all'|'focus';
export function graphIndex(g:Graph){
 const nodes=new Map(g.nodes.map(n=>[n.id,n]));
 const neighbors=new Map(g.nodes.map(n=>[n.id,new Set<string>()]));
 const incidents=new Map(g.nodes.map(n=>[n.id,[] as GraphEdge[]]));
 for(const e of g.edges){if(!nodes.has(e.source)||!nodes.has(e.target))continue;neighbors.get(e.source)!.add(e.target);neighbors.get(e.target)!.add(e.source);incidents.get(e.source)!.push(e);if(e.target!==e.source)incidents.get(e.target)!.push(e);}
 const score=(n:GraphNode)=>(n.important?100000:0)+(n.type==='PERSON'?1000:0)+Math.min(neighbors.get(n.id)?.size||0,100);
 const ordered=[...g.nodes].sort((a,b)=>score(b)-score(a)||a.label.localeCompare(b.label,'zh-CN')||a.id.localeCompare(b.id));
 return {nodes,neighbors,incidents,ordered};
}
export function visibleGraph(g:Graph,index:ReturnType<typeof graphIndex>,o:{mode:ViewMode;selected?:string|null;expanded?:Record<string,number>;revealed?:string[];pinned?:string[];types?:string[];inference?:string;perspective?:string}){
 const ids=new Set<string>();
 const addNeighbors=(id:string,count:number)=>{ids.add(id);const near=index.neighbors.get(id);let n=0;for(const item of index.ordered){if(near?.has(item.id)){ids.add(item.id);if(++n>=count)break;}}};
 if(o.mode==='all')g.nodes.forEach(n=>ids.add(n.id));
 else if(o.mode==='focus'&&o.selected)addNeighbors(o.selected,o.expanded?.[o.selected]??25);
 else index.ordered.filter(n=>n.in_adaptation!==false).slice(0,30).forEach(n=>ids.add(n.id));
 for(const [id,count] of Object.entries(o.expanded||{}))addNeighbors(id,count);
 [...(o.revealed||[]),...(o.pinned||[])].forEach(id=>ids.add(id));if(o.selected)ids.add(o.selected);
 let nodes=g.nodes.filter(n=>ids.has(n.id)&&(!o.types?.length||o.types.includes(n.type)||n.id===o.selected||o.pinned?.includes(n.id)));
 const kept=new Set(nodes.map(n=>n.id));
 let edges=g.edges.filter(e=>kept.has(e.source)&&kept.has(e.target)&&(o.inference!=='explicit'||!e.inferred)&&(o.inference!=='inferred'||e.inferred));
 if(o.perspective==='assets'){
  const stateNodes:GraphNode[]=[], stateEdges:GraphEdge[]=[];
  for(const n of nodes)for(const s of n.states||[]){const id=`state:${n.id}:${s.id}`;stateNodes.push({...n,id,label:s.label,type:'STATE',summary:`${n.label}的状态`,attributes:s.attributes,states:[s],important:false});stateEdges.push({id:`state-edge:${id}`,source:n.id,target:id,relation:'状态',inferred:false,reason:'',evidence:[],known_from:s.known_from,story_time:'',origin:'presentation',locked_fields:[]});}
  nodes=[...nodes,...stateNodes];edges=[...edges,...stateEdges];
 }
 return {nodes,edges};
}
export function applyOperations(base:Graph,ops:Operation[]):Graph{
 const nodes=new Map(base.nodes.map(n=>[n.id,n])),edges=new Map(base.edges.map(e=>[e.id,e]));
 for(const op of ops){
  if(op.op==='add_node'&&op.node)nodes.set(op.node.id,op.node);
  if(op.op==='update_node'&&op.node_id&&nodes.has(op.node_id))nodes.set(op.node_id,{...nodes.get(op.node_id)!,...op.patch});
  if(op.op==='delete_node'){nodes.delete(op.node_id!);for(const [id,e]of edges)if(e.source===op.node_id||e.target===op.node_id)edges.delete(id);}
  if(op.op==='add_edge'&&op.edge)edges.set(op.edge.id,op.edge);
  if(op.op==='update_edge'&&edges.has(op.edge_id!))edges.set(op.edge_id!,{...edges.get(op.edge_id!)!,...op.patch});
  if(op.op==='delete_edge')edges.delete(op.edge_id!);
  if(op.op==='merge_nodes'&&op.target_id){const target=nodes.get(op.target_id);if(!target)continue;const merged=(op.node_ids||[]).filter(id=>id!==op.target_id);const aliases=new Set(target.aliases);for(const id of merged){const n=nodes.get(id);if(n){aliases.add(n.label);n.aliases.forEach(a=>aliases.add(a));nodes.delete(id);}}nodes.set(target.id,{...target,aliases:[...aliases]});for(const [id,e]of edges){const next={...e,source:merged.includes(e.source)?target.id:e.source,target:merged.includes(e.target)?target.id:e.target};if(next.source===next.target)edges.delete(id);else edges.set(id,next);}}
 }
 return {...base,nodes:[...nodes.values()],edges:[...edges.values()]};
}
export const codepointSlice=(text:string,start:number,end?:number)=>Array.from(text).slice(start,end).join('');
export function edgeGeometry(sx:number,sy:number,tx:number,ty:number,index:number,total:number){const dx=tx-sx,dy=ty-sy,dist=Math.hypot(dx,dy)||1;const curvature=(total>1?(index%2===0?1:-1)*(0.16+0.1*Math.floor(index/2)):0.06)*(sx<tx||(sx===tx&&sy<=ty)?1:-1);return{sx,sy,tx,ty,cx:(sx+tx)/2-dy*curvature,cy:(sy+ty)/2+dx*curvature,dist};}
