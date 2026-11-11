# Pi 原计划交付核定

更新：2026-11-07。完整目标仍未达到真实供应商完成标准；下表区分接线与验收，不用分轮数量或UI评分拼成全项目验收。执行方式与安全约束遵循开发交接摘要。

| 原计划业务链 | 当前实现与可复现入口 | 尚需验证 |
| --- | --- | --- |
| 运行底座、项目隔离、协议/密钥、工具权限 | agent-runtime、backend/agent_runtime.py；pi-progress分轮协议/故障/安全测试 | 本机现有依赖下启动/停服已隔离验证；全新机器依赖安装未实测 |
| 持久会话、偏好、固定版本、压缩与恢复 | novel-memory、project-preferences、pi-run-checkpoints；真实SDK替身检查点/工具回执对账与显式恢复 | 真实长篇语义/压缩保真；无法证明的未知模型/回执仍停人工，不自动重发 |
| 五件套与受控业务工具 | comic-skills-migration；pi.5及旧包归档，175源静态处置，frame-plans受控查询 | 复杂代表格真实规则应用；静态处置不等于全部旧程序执行等价 |
| 骨架/细纲/脚本/包、图谱、选段与人工采用 | document-generation、production-text、text-selections、graph/verification | 真实供应商一话链、长篇语义质量/成本/耗时 |
| 三画风/资产、单格/批次、实图复查与一轮剧情返修 | style-tests、image-provider、image-postprocess、image-dependencies | 无参考/多参考/编辑/蒙版的真实供应商权限与效果，代表格检查/返修 |
| 用户批注定向编辑 | annotation-image-edits；固定底图/批注版本、内容digest和像素，既有job预览授权/候选/检查 | 本批独立实页主路径通过（pi-capability-annotation-ui-review），自动化完整709后端/206前端/47Node及构建通过；真实编辑质量。区域文字不是硬蒙版，旧批注讨论仍模拟 |
| 五类模型能力核对留存 | model-capabilities；仅明确选择已有回执核对，工具须SDK往返证据，公开配置变化过期 | 本批独立实页主路径通过（pi-capability-annotation-ui-review），自动化完整709后端/206前端/47Node及构建通过；核对不证明凭据仍可用或语义质量，不主动付费探测 |
| 批次容量、调用授权、时限、未知不重发与结果保全 | runtime-capacity、image-batch-control、image-provider、pi-run-checkpoints | 真实长批次耐久/费用；受控时钟测试不等于实际7小时跑满 |
| 页面、备份恢复与交付 | README、各轮独立UI报告、backup-restore、交付核对 | 全链真实小样交付核对；隔离合成恢复不等于真实用户库灾难恢复 |

## 范围决定

- 用户已明确额外全局token/金额硬限列后续增强；原20/50调用限额、容量、4/7h、真实用量/未知标识和明确付费授权保留。
- 高级图片工作区仍另专题。本轮批注编辑仅补原阶段五明确要求，不将旧模拟对话悄悄切到付费执行。
- 旧CSV完整ZIP、独立CAMERA/旧宿主时钟、XLSX单元格证据等按逐源记录说明兼容差异，不由旧文档自动扩大成新必需子系统；当前生效需求仍优先。

## 真实联调前置与记录

当前没有本轮真实供应商调用授权记录，也没有已核定的小样费用/次数范围。 2026-11-07只读核对默认data/workbench.sqlite的嵌套及旧单profile形状：text/image/vision均没有同时填写url与model；未读取钥匙串。这只是当时默认库检查，不代表其它数据目录或后续配置状态。不能读取聊天密钥或用替身代替真实验收。用户在应用内配置可用文本/图像/视觉凭据之后，先提出具体供应商/型号、样本、最多模型/工具/图像/视觉次数、允许编辑/返修范围及费用止损条件，经明确授权再运行。

按一格→一话扩大：先核真实图像/视觉/编辑能力与唯一调用回执，再核同一话细纲→脚本→生图包及代表格生成/检查/一次修图；候选采用与人工审核保留独立决定。长篇质量另定阅读覆盖、章节/事实抽样和成本样本，不因小样正确宣称读完全书。每项保留脱敏输入hash、型号/参数、请求编号、真实返回/像素、已知/未知用量、错误和人工结论；密钥与原著正文不进交接文档。

## 2026-11-07 启动交付检查

直接执行现有`./start.command`，PATH前置Node22.23.1，`COMIC_DATA_DIR`指向TemporaryDirectory，未操作默认用户库或设置供应商。实际8765上`/api/agent/health`返回ready/protocol1/provider_verified=false，`/`返回HTML、`/api/projects`返回列表；SIGINT后进程exit0，8765关闭，临时目录退出删除（session39487 exit0）。可复现：选择空闲8765、设置临时COMIC_DATA_DIR后运行启动脚本，用上述三个GET核对，再Ctrl+C并确认临时目录可删除。未调用配置/模型接口，未请求钥匙串读取或供应商调用；不证明全新机器安装、钥匙串权限或真实模型可用。

## 替身边界证据定位（2026-11-07恢复轮）

以下为已纳入上一稳定批709后端全量的自动化断言，当前逐项读源核对；不冒充新增实页证据。

- `backend/tests/test_annotation_image_edits.py::test_annotation_unknown_cannot_repost_and_stale_return_stays_candidate`：ReadTimeout后unknown，recover及换submission_id均409，实际transport仅1次。
- `test_late_annotation_change_keeps_paid_return_as_stale_candidate`：在transport返回期间改变批注，原返回仍保存，input_stale=true/adopted=0，采用409，只有1次调用。
- `test_history_or_unadopted_base_is_not_silently_replaced`：未采用或新head使旧底图预览409，零transport调用。
- `backend/tests/test_model_capabilities.py::test_tool_requires_exact_sdk_result_roundtrip_and_only_reads_checkpoint`：精确匹配host/SDK才verified，改result_hash后unverified，运行层只收到checkpoint_details；该测试用运行层替身，真实SDK往返另由本轮独立实页补验。
- `test_local_provider_is_unknown_and_mock_input_does_not_identify_provider`：localhost/IPv4/IPv6/远程均不能凭地址断言真实或替身；只有manifest明确模拟来源才mock。

本轮未改生产代码，因此不重复上轮已通过的全量；若独立补验发现缺陷，修复后再按受影响范围及稳定批次门槛验证。

2026-11-07恢复轮补验完成：独立实页text/tool/vision成功核对及unknown来源展示通过；实际SDK run f36a90d699524778a7afef14a382fd01的project_query回执matched/host_saved/received，正常授权视觉fixture完成，页面逐项选回执并保存，未手改账本。结合前批生成/编辑，五类成功核对现均有分轮实页证据，不拼成真实供应商验收或全站评分。未改生产代码，不重复全量；diff检查通过。报告docs/pi-capability-annotation-ui-review.md补验节；服务21997正常停服、临时数据/脚本清理、截图保留。剩余仍为真实配置/明确付费范围及真实语义质量成本验收，依用户安排待后续确认，完整目标不标完成。
