import { Type } from 'typebox';
import {createHash} from 'node:crypto';

export class ProjectBridge {
  constructor(ids,emit,onLimit=()=>{},maxCalls=50,hooks={}) { this.hooks=hooks; this.maxCalls=maxCalls; this.onLimit=onLimit; this.ids=ids; this.emit=emit; this.pending=new Map(); this.closed=false; this.count=0; }
  tools() {
    return [{name:'setup_catalog',label:'查找可用流程',description:'查询宿主本次冻结的流程目录。source=installed查共享已安装库（默认），source=bundled查应用附带但未安装的首版规则包；后者用返回handle=bundled:hash提出install_skill候选，安装后才能启用，不代表完整五件套/脚本已迁移。query匹配名称、id、风格标签与阶段；start/limit分页，未返回或无命中不代表完整库已读。返回固定hash可用installed:hash提出项目选择；工具不安装、不启用、不读取小说或执行脚本。',
      parameters:Type.Object({source:Type.Optional(Type.Union([Type.Literal('installed'),Type.Literal('bundled')])),query:Type.Optional(Type.String({maxLength:200})),start:Type.Optional(Type.Integer({minimum:0})),limit:Type.Optional(Type.Integer({minimum:1,maximum:50}))},{additionalProperties:false}),
      execute:(callId,args,signal)=>this.call('setup_catalog',callId,args,signal),
    },{name:'project_query',label:'查询项目证据',description:'读取宿主冻结的项目资料。catalog列出资料，record按id读取固定版本，search_novel按query检索原著，source按文档id/start读取正文，graph查询知识图谱（layer=original查原著，默认adaptation查当前改编）；skill按id=来源固定包hash、query=包内资料路径或skill://依赖id@精确版本/路径读取流程规则；跨包仅限本次项目明确启用并冻结的声明依赖，引用资料不自动启用其主流程（skill query最多400字符，其他query最多200）（start分段），query=@files按start/limit分页列目录。novel_summary按id=文档编号读取固定已发布任务的模型摘要：query=volume或chapter分页，chapter:解析章节序号或volume:卷名可定位；search:关键词查摘要，unit:单元编号按start分段读全文；同章/卷可有多个单元，不可漏掉分页。摘要不是原文引文，需source核实。frame_plan以id指定本次固定已采用脚本，先不传plan读取该整话源序；再传plan=[{id,ratio,reason}]按原序覆盖全话，校验content_balanced_ratios_v1的分布，不改记录/采用/生图，不证明理由或像素正确。引用原著时保留文档/解析版本/起止位置。coverage标记解析缺页/OCR状态；分段、无命中或limit_reached均不代表读完全书。',
      parameters:Type.Object({action:Type.Union(['catalog','record','search_novel','source','graph','skill','novel_summary','frame_plan'].map(v=>Type.Literal(v))),id:Type.Optional(Type.String()),query:Type.Optional(Type.String({maxLength:400})),start:Type.Optional(Type.Integer({minimum:0})),limit:Type.Optional(Type.Integer({minimum:1,maximum:50})),layer:Type.Optional(Type.Union([Type.Literal('original'),Type.Literal('adaptation')])),plan:Type.Optional(Type.Array(Type.Object({id:Type.String({minLength:1}),ratio:Type.Union(['9:16','3:4','4:5','1:1','5:4','16:9'].map(v=>Type.Literal(v))),reason:Type.String({minLength:1,maxLength:2000})},{additionalProperties:false}),{minItems:1,maxItems:1000}))},{additionalProperties:false}),
      execute:(callId,args,signal)=>this.call('project_query',callId,args,signal),
    },{name:'propose_style_tests',label:'提出同组三套画风测试',description:'仅新style阶段开放。先查询本次首选原著和已采用审核细纲。为同一主角/主场景/动作提出恰好三个不同二维画风，每套一张覆盖身份/多视角/表情/剧情场景的测试板；共有输入不能随画风换人换景。outline_id来自固定资料，source_ranges是首选原著的解析版本及真实字符起止，不接受客户端引文，人物/场景名称须在原文出现。directions只表达线条、比例、上色、阴影。保存方案不生图，各套须用户预览并另行授权，不能伪造审核或全书通读。',parameters:Type.Object({title:Type.String({minLength:1,maxLength:120}),outline_id:Type.String(),representative:Type.Object({character:Type.String({minLength:1,maxLength:200}),appearance:Type.String({minLength:1,maxLength:3000}),scene:Type.String({minLength:1,maxLength:200}),setting:Type.String({minLength:1,maxLength:3000}),action:Type.String({minLength:1,maxLength:3000})},{additionalProperties:false}),directions:Type.Array(Type.Object({name:Type.String({minLength:1,maxLength:80}),line:Type.String({minLength:1,maxLength:800}),proportions:Type.String({minLength:1,maxLength:800}),color:Type.String({minLength:1,maxLength:800}),shadow:Type.String({minLength:1,maxLength:800})},{additionalProperties:false}),{minItems:3,maxItems:3}),source_ranges:Type.Array(Type.Object({document_id:Type.String(),parse_version:Type.Integer({minimum:1}),start:Type.Integer({minimum:0}),end:Type.Integer({minimum:1})},{additionalProperties:false}),{minItems:1,maxItems:5})},{additionalProperties:false}),execute:(callId,args,signal)=>this.call('propose_style_tests',callId,args,signal),
    },{name:'propose_image',label:'提出画风或资产生图方案',description:'仅新画风/资产阶段开放。提出单张新建/重生成方案，不调用图像模型、不改原稿。title与prompt须具体；target_id仅本次明确附加的本阶段目标，省略为新建；references为本次冻结目录中已采用审核的实际style/asset图片id，不得传路径、URL、APIkey或模型参数。资产自动固定本次已确认画风；每次最多16张含底图和画风。用户在方案中核对后先创建预览，再明确授权1张，候选仍未采用。不能声称已观察像素或已生成。',parameters:Type.Object({title:Type.String({minLength:1,maxLength:200}),prompt:Type.String({minLength:1,maxLength:32000}),target_id:Type.Optional(Type.String({minLength:1,maxLength:100})),category:Type.Optional(Type.Union(['人物','场景','道具'].map(v=>Type.Literal(v)))),references:Type.Optional(Type.Array(Type.String(),{maxItems:16}))},{additionalProperties:false}),execute:(callId,args,signal)=>this.call('propose_image',callId,args,signal),
    },{name:'propose_changes',label:'提出修改候选',description:'保存可供用户核对和明确采用的修改候选，不修改成品。record只能改本次会话附加的本阶段资料，不可改话格身份/引用/审核。文档用patch.text新正文，脚本用原字段，生图包可分别优化提示词。memory阶段可改graph_node基本信息或graph_edge关系说明；不能改证据或资产。script阶段script_create以id指定已附加的当前脚本作为话/批次锚点，patch包含未用的整数panel及脚本文本字段，不重排旧格号；script_delete以id指定附加脚本，patch只含非空reason，用户采用后会撤下同格包/图及关联试制确认，保留历史。请先查询固定版本内容再提出完整修改。',
      parameters:Type.Object({title:Type.String({minLength:1,maxLength:200}),changes:Type.Array(Type.Object({target:Type.Union(['record','graph_node','graph_edge','script_create','script_delete'].map(v=>Type.Literal(v))),id:Type.String(),patch:Type.Record(Type.String(),Type.Any())},{additionalProperties:false}),{minItems:1,maxItems:100})},{additionalProperties:false}),
      execute:(callId,args,signal)=>this.call('propose_changes',callId,args,signal),
    }];
  }
  call(name,callId,args,signal) {
    return new Promise((resolve,reject)=>{
      if(this.closed || signal?.aborted) return reject(new Error('cancelled'));
      if(this.count>=this.maxCalls) {this.close();this.onLimit();return reject(new Error('tool_limit'));}
      try{this.hooks.beforeDispatch?.(callId,name,args);}catch(e){return reject(e);}
      this.count++;
      const cancel=()=>{this.pending.delete(callId);reject(new Error('cancelled'));};
      signal?.addEventListener('abort',cancel,{once:true});
      this.pending.set(callId,{resolve,reject,cleanup:()=>signal?.removeEventListener('abort',cancel)});
      this.emit({...this.ids,type:'tool_request',tool_call_id:callId,name,arguments:args,input_hash:createHash('sha256').update(JSON.stringify(args)).digest('hex')});
    });
  }
  accept(message) {
    if(message.run_id!==this.ids.run_id) return false;
    const pending=this.pending.get(message.tool_call_id);
    if(!pending) return false;
    this.pending.delete(message.tool_call_id);pending.cleanup();
    try{this.hooks.afterReceipt?.(message.tool_call_id,Boolean(message.error),message);}catch(e){pending.reject(e);return false;}
    if(message.error) pending.reject(new Error('tool_denied'));
    else pending.resolve({content:[{type:'text',text:JSON.stringify(message.data)}],details:{}});
    return true;
  }
  close() {this.closed=true;for(const p of this.pending.values()){p.cleanup();p.reject(new Error('cancelled'));}this.pending.clear();}
}
