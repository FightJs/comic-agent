# 长篇小说知识图谱实施契约

用户批准2026-11-04方案。全量要求以本聊天用户最后一条完整计划为准。本文固定实现边界、接口及协作分工。

## 产品约束
剧情/资产双视角、人物关系主干30、完整图不截断、局部一跳25每次12。实体PERSON/LOCATION/ORGANIZATION/OBJECT/OTHER。事件为摘要和证据。名称/别名搜索包含隐藏节点。多边方向、推断标记、原著/改编视角和章节/话过滤。人工编辑保护、合并、删除抑制、revision历史恢复、来源证据定位。人物单身份多state，状态一主参考多用途补图。原著明确事实和有证据推断分开。
TXT/MD/DOCX/PDF，GB18030，单完整文件500万字级，解析自动启动真实抽取，3000字/200重叠、不跨章节。持久检查点，并发2，每块最多3次尝试。抽取+章卷摘要+全书实体整理完成才能原子发布。缺配置等待配置，失败不冒充空结果。暂停/继续/取消/重试，重启手动续跑。缓存内容+模型+schema，定位另绑定解析版本。所有引用必须后端校验，Unicode codepoint offsets。
默认当前改编优先，显式清空不回退；人工锁优先。一个当前确定细纲，生成即时/保存10秒后队列合并、最新版本发布。明确合并产生改编实体original_ids而非删除原著身份。未提及仅未采用。资产确认采用核验审核精确版本和当前画风、稳定entity/state关联、视觉字段回写、失效追踪。模拟不进正式图。

## 固定公开API（普通JSON，非Resp包裹）
所有路径前缀 /api/projects/{pid}，错误FastAPI detail字符串。
GET /graph?layer=adaptation|original&at=N （at省略全书，adaptation按话、original按章）:
{revision:number,status:'empty'|'ready',nodes:Node[],edges:Edge[],conflicts:Conflict[], outline_id:string|null,outline_version:number|null}
Node={id,label,type,aliases:string[],summary:string,important:boolean,attributes:Record<string,string>,states:State[],evidence:Evidence[],known_from:number|null,source:string,locked_fields:string[],original_ids?:string[],in_adaptation?:boolean}
State={id,label,attributes:Record<string,string>,known_from:number|null,assets:AssetRef[]}
AssetRef={asset_id,version,role,url?,valid:boolean,reason?:string}
Edge={id,source,target,relation,inferred:boolean,reason:string,evidence:Evidence[],known_from:number|null,story_time:string,origin:string,locked_fields:string[]}
Evidence={document_id,parse_version:number,chapter:number,start:number,end:number,quote:string,source_kind?:string,record_id?:string,record_version?:number}
Conflict={id,target_id,field,manual:any,incoming:any,source:string}
PATCH /graph {expected_revision,operations: Operation[]} -> 最新graph（adaptation投影）
Operations: {op:'add_node',node}; {op:'update_node',node_id,patch}; {op:'delete_node',node_id}; {op:'add_edge',edge}; {op:'update_edge',edge_id,patch}; {op:'delete_edge',edge_id}; {op:'merge_nodes',node_ids:string[],target_id}; {op:'unlock',node_id,fields:string[]}; {op:'resolve_conflict',conflict_id,choice:'manual'|'incoming'}。
GET /graph/history -> [{revision,created,summary}]
POST /graph/restore {expected_revision,revision} -> graph
GET /graph/context?entity_id=&layer=&at= -> filtered graph/evidence 同一过滤规则
GET /graph/entities/{id}?layer=&at= -> Node（过滤后查找）

GET /documents -> Document[]
POST /documents multipart file,encoding(auto默认) -> Document（保留original记录但不要在records列表复制500万字正文，老TXT兼容）
Document={id,title,parse_version,status,char_count,chapter_count,chapters:Chapter[],warnings:string[]}
Chapter={index:number,title,start,end,volume?:string} 章节index从1开始
GET /documents/{id}/text?parse_version=&chapter=&start=&end= -> {text,start,end,chapter?,title?} 用codepoint
POST /documents/{id}/reparse -> Document/job
PUT /documents/{id}/chapters {parse_version,chapters:[{title,start}]} -> Document
GET /graph/jobs -> Job[]
POST /graph/jobs {document_id} -> Job
POST /graph/jobs/{id}/{pause|resume|cancel|retry} -> Job
Job={id,kind,status,stage,completed,total,error:string|null,document_id?,created,usage?:{input_tokens,output_tokens},issues?:any[]}
GET /graph/outline -> {record_id,version,status}（无选择null）
PUT /graph/outline {record_id,version} -> selection
POST /graph/assets/confirm {asset_id,version,entity_id,state_id,role:'main'|string} -> graph
POST /graph/assets/draft {entity_id,state_id} -> RecordItem资产草稿

模型配置继续GET/PUT /api/settings?purpose=text，新增purpose=parse，MinerU可选。当前文本模型走下方Pi统一入口，凭据由Python钥匙串经管道注入Node内存；测试不得使用真实钥匙串或真实供应商。

## 分工与集成
后端worker拥有 backend/ 下所有新增graph/document模块、backend/app.py/store.py/workflow.py必要增量修改、依赖requirements及后端测试。根agent拥有frontend/全部、docs和集成验证。禁止覆盖现有工作、禁止提交用户已有改动。接口调整先发消息。
前端统一Canvas2D+worker布局+空间索引，React负责属性/列表/编辑。保持DESIGN.md。实际页面隔离数据审核ui_reviewer >=90无重要问题。

## 验收
500万字解析/调度测试、1万节点3万边画布实测、真实供应商与替身区分。测试覆盖原子发布、版本迟到、取消恢复、隔离、manual保护、alias不乱合并、过滤所有字段防剧透、细纲debounce、资产有效性。先红后绿。最终backend pytest、frontend vitest、build及独立浏览器验收。

## 验收中补齐的接口细节

`POST /graph/evidence` 接收完整 Evidence；`GET /documents/{id}/search?q=&parse_version=` 返回匹配位置及总量。关系同样可使用 `unlock`（edge_id）。Conflict 包含可选 evidence。资产确认支持显式 `rebind:true`，保留图片版本及旧绑定来源；普通错绑仍拒绝。历史恢复遇到后续资产身份依赖返回409，避免破坏绑定。


## Pi统一模型入口增量（2026-11-05）

图谱文本调用改为`PiRuntime.request('complete')`→Node共享适配器。每次只有系统约束和本单元冻结文本，无工具、无创作会话历史、无会话文件；不再使用独立HTTPX生产调用，也不保留旧端点回退。缓存签名包含协议与适配器版本，旧结果不会跨协议误复用。切块、检查点、引用证据校验、全书整理及原子发布不变。

请求完成后先记账，随后检查取消/结构/证据；已取消或不合法结果不能发布，但仍保留已返回用量。未返回用量时`usage.unknown=true`，已知部分继续累计，界面明确总量未知。已返回token不等于已知金额。

讨论和单次调用共享`agent-runtime/src/model.mjs`，供应商错误/最终消息递归清除本次凭据，流式delta保留可能的密钥前缀以处理跨片段回显。隔离假供应商回归检查协议及SDK会话文件，无真实密钥、无付费调用。Chat-Completions本机完整发布链路已验证；Responses/Anthropic仅复用SDK适配接口，真实供应商兼容性仍待验收。完整测试结果见`docs/pi-progress.md`本轮记录。


## 文档生产衔接（2026-11-05）

生成细纲HTML直接从第N话标题开始，不带未分配的全书总标题；记录名保存总标题。采用才建立对应版本的话索引。图谱选择/API/自动任务共用`store.is_primary`，候选、拒绝、待处理或未采用记录不能作为正式改编细纲；正常人工保存当前正式文档仍自动同步。真实Pi SDK+本机HTTP替身已串通文档生产、明确采用、图谱单次模型调用与原子发布，outline_version匹配；不表示真实模型语义验收。
