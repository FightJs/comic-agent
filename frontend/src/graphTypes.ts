export type Evidence = {document_id:string;parse_version:number;chapter:number;start:number;end:number;quote:string;source_kind?:string;record_id?:string;record_version?:number};
export type AssetRef = {asset_id:string;version:number;role:string;url?:string;valid:boolean;reason?:string};
export type GraphState = {id:string;label:string;attributes:Record<string,string>;known_from:number|null;assets:AssetRef[]};
export type GraphNode = {id:string;label:string;type:string;aliases:string[];summary:string;important:boolean;attributes:Record<string,string>;states:GraphState[];evidence:Evidence[];known_from:number|null;source:string;locked_fields:string[];original_ids?:string[];in_adaptation?:boolean};
export type GraphEdge = {id:string;source:string;target:string;relation:string;inferred:boolean;reason:string;evidence:Evidence[];known_from:number|null;story_time:string;origin:string;locked_fields:string[]};
export type Conflict = {id:string;target_id:string;field:string;manual:unknown;incoming:unknown;source:string;evidence?:Evidence[]};
export type Graph = {revision:number;status:string;nodes:GraphNode[];edges:GraphEdge[];conflicts:Conflict[];outline_id:string|null;outline_version:number|null};
export type Operation = {op:string;node?:GraphNode;node_id?:string;patch?:Record<string,unknown>;edge?:GraphEdge;edge_id?:string;node_ids?:string[];target_id?:string;fields?:string[];conflict_id?:string;choice?:string};
export type GraphJob = {id:string;kind:string;status:string;stage:string;completed:number;total:number;error:string|null;document_id?:string;created:string;usage?:{input_tokens:number;output_tokens:number;unknown?:boolean};issues?:unknown[]};
export type GraphDocument = {id:string;title:string;parse_version:number;status:string;char_count:number;chapter_count:number;chapters:{index:number;title:string;start:number;end:number;volume?:string}[];warnings:string[]};
export const TYPE_LABELS:Record<string,string>={PERSON:'人物',LOCATION:'场景',ORGANIZATION:'组织',OBJECT:'道具',OTHER:'其他',STATE:'状态'};
export const newId=()=>crypto.randomUUID();
export const emptyGraph:Graph={revision:0,status:'empty',nodes:[],edges:[],conflicts:[],outline_id:null,outline_version:null};
export const blankNode=():GraphNode=>({id:newId(),label:'未命名人物',type:'PERSON',aliases:[],summary:'',important:false,attributes:{},states:[],evidence:[],known_from:null,source:'manual',locked_fields:[]});
export const blankEdge=(source:string,target:string):GraphEdge=>({id:newId(),source,target,relation:'关联',inferred:false,reason:'',evidence:[],known_from:null,story_time:'',origin:'manual',locked_fields:[]});

export const FIELD_LABELS:Record<string,string>={__presence:'实体保留',label:'名称',type:'类型',aliases:'别名',summary:'简介',important:'重要性',attributes:'属性',states:'状态',evidence:'依据',known_from:'披露进度',original_ids:'原著身份',in_adaptation:'改编范围',source:'起点',target:'终点',relation:'关系名称',inferred:'推断标记',reason:'推断说明',story_time:'发生时期'};
export const ROLE_LABELS:Record<string,string>={main:'主参考',supplemental:'补充参考',front:'正面补充',side:'侧面补充',back:'背面补充',expression:'表情补充',detail:'局部补充'};
