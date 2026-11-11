# Pi剩余链路集中集成

2026-11-06用户要求加速；原目标与安全标准不变。基线：工具回执批次后端556/Node39通过，独立代码复审通过。开发相关测试，稳定批次再统一全量/实际页面独立审核，定点修复复审。

## 当前批次与所有权

1. 主agent：依赖/协议、共享入口接线、前端恢复入口、交接和验收；不改worker所属文件。
2. confirmed_unsent_retry：仅image_provider.py与独立重试测试；先核定确认未发送与attempt/授权约束，安全做不到则报告接线需求。
3. tool_recovery_node：仅新增tool-recovery.mjs与独立测试。私有输入project_id/session_id/run_id/recovery_id/receipts；receipt含call_id/name/node_input_hash/result_hash/result_json。恢复不调用模型/工具；验证SDK准确分支与所有待补回执、保留原账本快照、可幂等重试跨文件落盘，最终旧计数不变落干净paused。
4. tool_recovery_host：仅新增tool_recovery.py与独立测试。事务认领/冻结证据、校验原审计与回执摘要、生成私有请求/公开白名单结果；共享讨论和生产接线由主agent负责。
5. skill_pi4_source_review：能力映射JSON与专项测试，未改原清单完成状态/运行包；delivery_readiness：交付数据库证据核对模块及专项，主agent接只读GET。其余链路审计已完成，不重复已实现功能。

## 恢复协议约束

严格confirm授权仅补已有宿主结果，不授予新调用；后续继续沿原20/50明确许可。原运行停止/非取消/无续接，模型请求全返回，实际会话文件及assistant叶存在；未知模型、缺回执、旧无摘要、分支/输入冲突均阻止。宿主固定recovery_id和证据摘要，Node同步SDK文件与持久恢复元数据后才发布paused检查点；失败/重启仍查同一恢复编号，不重做业务动作。保存原账本及append-only原分支，计数/用量不归零。先保守支持最后一个完整可核对的assistant工具组，多组/有后继assistant等无法证明的情况拒绝，不伪造恢复。

## 后续集中验收

原版本/偏好/Skill/供应商绑定、模拟来源、候选人工采用及审核保留。合成项目/假密钥/本机替身，覆盖正常/重复并发/落盘失败/跨项目/输入变化/取消及明确续接；前端实页独立审核。真实供应商小样、长篇语义与费用单列待验，不能拿替身结果代替。备份恢复、必要脚本映射和全量范围最终核定见本批交接，不把历史待办当新功能要求。

## 核定后的余项与依赖

- 已有配置/安装、卷章记忆/图谱、文本生产与修改、三画风、逐格依赖/实图检查/一轮返修；继续做最终真实供应商验证，不因旧文档待办重复开发。
- 优先完整链：宿主结果核对→SDK准确分支补消息→干净暂停点→用户明确续接；Node/宿主、API/持久锁/版本取消守卫、UI与实际SDK中断端到端已接；独立代码复审通过，独立实页补验两关键分支后99/100通过（仅本轮范围），一般项为生产取消后焦点未回稳定位置。未知模型或证据不全仍拒绝恢复。
- 确认无图技术重试：先完成明确额外网络重试授权0–4、每次attempt证据与提交守卫，再接provider/job/batch与UI；默认0，未知/拒绝/收到响应绝不重试。本批先修响应后异常误标not_sent。
- 交付核对：只读源格/主图/精确版本报告/遗留问题，独立模块与GET已接；界面已接并完成相关自动化，独立独立实页补验两关键分支后99/100通过（仅本轮范围），一般项为生产取消后焦点未回稳定位置。数据库ready不证明磁盘像素或全话完成。
- Skill按能力组映射（capability-mapping.json），保留创作规则，未审程序仍未结案；旧全职责时钟/独立CAMERA/跨机可执行ZIP不从源合同自动扩大成本项目必需子系统。全局token/金额预算仍保留后续导航决策，不能混称原阶段六已有显式硬限。
- 最终停服备份/恢复步骤与隔离恢复验证、真实供应商一话/复杂代表格及长篇质量费用仍待。高级图片工作区按原用户要求另专题。


## 下一批所有权与门槛

- confirmed_unsent_retry：仅新增image_attempts.py及对应测试，严格0–4策略与逐次持久证据底座；主agent负责后续provider/job/预览冻结及提交守卫接线，未接线不称自动重试可用。
- delivery_readiness：仅新增隔离备份恢复核验脚本/对应测试及docs/backup-restore.md，复用既有存储，不触碰真实库/钥匙串或启动付费任务。
- 主agent：共享协议/路由/授权与页面集成、上一批UI缺证据分支已补验通过、专题交接。下一稳定批次统一全量与独立UI审核。


## 确认未发送技术重试集成批次

所有权：confirmed_unsent_retry负责image_provider及独立attempt-provider测试；recovery_business_routes负责image_jobs/image_batches及job-retry测试；recovery_frontend负责ImageGeneration/ImageBatches与对应测试；主agent负责agent_image_plans/style_batches、AI单图/三套方案及整组授权界面、共享旧测试/文档/QA接线。模块均已接通，未变默认0、未知不重发及人工采用边界。

策略严格0–4进入首次预览签名/manifest/授权，业务图像×(1+次数)给出物理上限；provider一次只POST一次，job循环每次重新占槽并复核版本/取消/批次时钟；独立返修继承策略，依赖改绑仅未提交，重启须明确恢复且余量不重置。历史没有字段不补授权或已知网络上限。代码审历史UI伪确定P2已RED修复并定点复审关闭。

前端完整190/40、Node47与build2.64秒已通过；后端首全量683通过/1旧测试缺新授权摘要失败，修测试后逐格15通过，最终完整后端684/360.08秒通过。独立实页99/100通过（仅本轮范围），一般项为三套整组checkbox与说明分行，逐格返修批次/独立AI单图本轮仅验固定预览；证据见pi-progress及pi-technical-retry-ui-review。隔离服务与数据已清理。下一必需工作仍有必要Skill语义结案、全局预算范围及真实供应商/长篇质量费用验证。


必要Skill定点核定（非全源结案）：下一批最小内容补充为物理/批准布局/剧情硬要求与画风同时满足、先调整机位裁切而不弱化剧情对象，以及fresh独立重做/明确复用/恢复原批次的来源边界；同一未知调用不能借重做抹账本。准确源条款production-foundation.md、stage-input-audit.md、stage-prompt-package.md、task-origin.md。应补既有资料并归档升级包、核80k闭包，不新增通用语义门禁。53资料/121脚本/1部分脚本仍需逐来源处置依据，组映射不等于结案；不由旧宿主合同自动新增CAMERA/完整时钟/可执行ZIP。当前技术重试provider/jobs/UI已完成接线，不再沿用该核定时的“待接线”。


## Skill逐源处置与pi.5批次（进行中）

所有权：skill_pi4_source_review负责pi.5既有资料/入口/source-index/五包与pi.4字节归档及专项；recovery_frontend负责source-decisions/creative-rules.json（45源），confirmed_unsent_retry负责dispatch-recovery.json（47源），recovery_business_routes负责review-delivery.json（33源），delivery_readiness负责inputs-environment.json（50源）；主agent负责统一验证、清单交叉索引与交接，manual_pause_code_review独立核规则/压力题。各自不改他人文件，最终稳定批次统一全量，未改变原包项目选择。

四份处置按每源hash/准确锚点/关键行为/宿主证据/不迁理由/真实残余记录，不将未注册旧程序伪称已运行等价；不能确认的保留pending或needs_implementation。pi.5已完成且独立核定，最大阶段闭包79815/80000；并发读取不能冒充未改pi.4压力基线，旧规则原已有同时满足约束/先机位裁切，不声称模型提升。

范围澄清已向用户发出：原阶段六正文明确调用20/50、并发、批次4/7h及真实用量，未显式要求全局token/金额硬限；该项仅在后续导航/执行记录出现且无额度。用户尚未补范围前，继续原明确要求，额外硬限不阻塞本轮独立工作，也不把历史导航记录误称用户已批准的详细预算策略。

2026-11-06用户已答复范围澄清：按原计划交付，额外全局token/金额硬限列后续增强。前文“尚未补范围”及全局预算待办保留历史语境，本次不再以此阻断；20/50、容量、4/7h、用量及原付费授权保持。


## 2026-11-07：原合同最后功能缺口集成（进行中）

核定五类模型能力证据留存、用户批注定向图像编辑仍缺，不扩大高级图片工作区。能力核对复用已授权业务回执、不新发付费探测：delivery_readiness仅model_capabilities.py/专项/操作文档，recovery_frontend仅新ModelCapabilities组件/CSS/测试。批注编辑复用image_jobs/provider账本：recovery_business_routes仅image_jobs.py/annotation_image_inputs.py/专项/操作文档，confirmed_unsent_retry仅ImageGeneration及专项。主agent仅app注册/Auxiliary/Images共享入口、整合与验收交接；manual_pause_code_review只读独立代码审；稳定后统一全量与独立UI。当前底图及批注服务端版本冻结，区域/保护文本不冒充硬蒙版；普通包生图不放宽。

本批已收口：后端完整709/369.32s、前端206/43文件、Node47与build2.77s通过；独立代码及实页主路径通过，无全站评分，未实页边界详列报告。隔离服务16215停服并清理。当前仅真实供应商/长篇质量费用及实际环境验收待，不因已实现接线或替身结果标记完整goal完成；核定表docs/pi-final-acceptance.md。
