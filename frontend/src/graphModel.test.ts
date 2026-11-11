import { describe, expect, it } from 'vitest';
import { visibleGraph, graphIndex, applyOperations, codepointSlice, edgeGeometry } from './graphModel';
import type { Graph, GraphNode } from './graphTypes';
const node = (id: string, important = false): GraphNode => ({id,label:id,type:'PERSON',aliases:[],summary:'',important,attributes:{},states:[],evidence:[],known_from:null,source:'manual',locked_fields:[]});
const graph: Graph = {revision:1,status:'ready',nodes:Array.from({length:50},(_,i)=>node('n'+i,i===49)),edges:Array.from({length:49},(_,i)=>({id:'e'+i,source:'n0',target:'n'+(i+1),relation:'认识',inferred:false,reason:'',evidence:[],known_from:null,story_time:'',origin:'manual',locked_fields:[]})),conflicts:[],outline_id:null,outline_version:null};
describe('graph exploration',()=>{
 it('keeps important characters in backbone, complete graph is not truncated',()=>{ const idx=graphIndex(graph); expect(visibleGraph(graph,idx,{mode:'overview'}).nodes.map(n=>n.id)).toContain('n49'); expect(visibleGraph(graph,idx,{mode:'all'}).nodes).toHaveLength(50); });
 it('explores one hop in pages and keeps revealed hidden search result',()=>{const idx=graphIndex(graph); expect(visibleGraph(graph,idx,{mode:'focus',selected:'n0'}).nodes).toHaveLength(26); expect(visibleGraph(graph,idx,{mode:'focus',selected:'n0',expanded:{n0:37}}).nodes).toHaveLength(38); expect(visibleGraph(graph,idx,{mode:'overview',revealed:['n45']}).nodes.map(n=>n.id)).toContain('n45');});
 it('filters inference and avoids dangling edges',()=>{const g={...graph,edges:graph.edges.map(e=>({...e,inferred:true}))}; const view=visibleGraph(g,graphIndex(g),{mode:'all',inference:'explicit'}); expect(view.edges).toHaveLength(0);});
 it('does not change base graph during editing and removes incident edges',()=>{const changed=applyOperations(graph,[{op:'delete_node',node_id:'n0'}]);expect(changed.edges).toHaveLength(0); expect(graph.nodes).toHaveLength(50);});
 it('merges references without leaving orphan edges',()=>{const g=applyOperations(graph,[{op:'merge_nodes',node_ids:['n1','n2'],target_id:'n1'}]);expect(g.nodes).toHaveLength(49);expect(g.edges.some(e=>e.target==='n2')).toBe(false);});
 it('converts codepoint evidence offsets and separates parallel edges',()=>{expect(codepointSlice('甲😀乙丙',1,3)).toBe('😀乙');expect(edgeGeometry(0,0,100,0,0,2).cy).not.toBe(edgeGeometry(0,0,100,0,1,2).cy);});
});
