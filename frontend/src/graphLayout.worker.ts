import { forceSimulation, forceManyBody, forceLink, forceCollide, forceX, forceY, type SimulationNodeDatum } from 'd3-force';
type LayoutNode=SimulationNodeDatum & {id:string;type:string};
let generation=0;
self.onmessage=(event:MessageEvent)=>{
 const {nodes,edges,mode}=event.data as {nodes:LayoutNode[];edges:{source:string;target:string}[];mode:string};
 const token=++generation;
 const kinds=[...new Set(nodes.map(n=>n.type))];
 nodes.forEach((n,i)=>{if(!Number.isFinite(n.x)){const angle=i*2.3999632297,r=Math.sqrt(i)*105;n.x=Math.cos(angle)*r;n.y=Math.sin(angle)*r;}});
 const simulation=forceSimulation(nodes).stop().randomSource(()=>0.5)
 .force('charge',forceManyBody().strength(-230).distanceMax(900))
 .force('link',forceLink<LayoutNode,any>(edges.map(e=>({...e}))).id(n=>n.id).distance(175).strength(0.2))
 .force('collide',forceCollide<LayoutNode>(68).iterations(1))
 .force('x',forceX<LayoutNode>(n=>mode==='types'?(kinds.indexOf(n.type)-(kinds.length-1)/2)*500:0).strength(mode==='types'?0.09:0.003))
 .force('y',forceY(0).strength(0.003));
 let tick=0;const max=nodes.length>2000?65:110;const started=performance.now();
 const batch=()=>{if(token!==generation){simulation.stop();return;}for(let i=0;i<5&&tick<max;i++,tick++)simulation.tick();self.postMessage({positions:nodes.map(n=>({id:n.id,x:n.x,y:n.y})),progress:Math.round(tick/max*100),elapsed:performance.now()-started});if(tick<max)setTimeout(batch,0);else simulation.stop();};batch();
};
