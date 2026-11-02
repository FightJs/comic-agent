# 批次制作独立代码审查

审查时间：2026-11-02。范围：重设计规格、backend/workflow.py、backend/app.py 接入及 Workflow/Production/Images/AnnotationCanvas 数据流。未修改实现代码。重点为数据正确性，不重复浏览器审美/手势审查。

## 必须修复

### [P1] 首次生成没有预留唯一话格目标，并发提交产生两个主稿

位置：`backend/workflow.py:182-192`（`range` 同类问题在 170-172）；前端相关调用 `frontend/src/Production.tsx:469,512,526`。

`existing_package` / `existing_image` 在任务提交时查询并冻结；数据库仅按 submission token 去重，没有把“该话格已有待执行的首次生成”纳入检查。第一次任务尚未输出时，第二个不同 token 的任务也冻结 `None`，两个任务完成均创建没有 `candidate_for` 的主记录。range 同样只检查已经产出的脚本。前端包/图片按钮每次调用 submitJob 默认产生新 token，响应丢失后重试也失去请求级幂等性。

已用临时数据库实际复现：创建第1话第1格脚本，用 ThreadPoolExecutor 同时发送两个 operation=package 请求，refs 完全相同、submission_id 分别为 a/b。两请求均 200；完成后该话格有两个 package，candidate_for 均 None。UI 及后续 existing() 只能任意选择其中一个，破坏唯一身份和逐格采用流程。

建议：提交事务中预留唯一目标，或识别并拒绝/复用同话格待执行首次生成；完成时也应确保唯一主稿。包/图片 UI 对同一提交尝试保存 token，明确成功后才换 token。增加并发首包、首图、范围重叠测试。

### [P1] 编辑包后立即生图会发送旧提示词，保存失败也不会阻止提交

位置：`frontend/src/Production.tsx:524-526`（同类脚本→包调用 512）；相关 `frontend/src/useDraft.ts:95-116`。

PackageDetail 的本地 useDraft 与上层 picked records 分离；直接编辑有900ms自动保存延迟，而生成按钮只检查 picked 的服务器版本 prompt。编辑最终提示词后立即生成，提交仍是编辑前的 record/version；后端只验证版本等于服务器 head，因此若保存尚未开始，旧提示词任务可以成功排队。保存冲突/失败时也同样可继续提交旧内容。实际可见编辑与任务冻结的最终文本不一致。

复现步骤：选中一个有完整提示词的包，打开详情，将最终提示词 A 改为 B，900ms 内点击“生成所选图片”。查看任务 payload.snapshots[0].content.prompt，仍为 A。将保存请求置为失败后再点击也会发送旧稿。代码路径已核对，未用真实浏览器计时复现。

建议：提交前显式 flush 选中格草稿并使用返回版本；保存失败/冲突时保留本地内容且阻止该格提交。至少对 dirty/saving/failed 状态禁用生成并说明原因。脚本→包同样需要保证所见稿与提交稿一致。

### [P2] 修图没有校验用户确认的批注版本，跨标签页修改会悄然换入另一套要求

位置：`backend/workflow.py:179-181`；`frontend/src/Workflow.tsx:532-549` 提交结构。

repair 请求只发送图片 id/version，不发送确认过的 annotation version/items。服务器在提交时直接取最新批注，前端 annotationsReady 仅判断当前页保存状态和 localStorage 是否有草稿。另一标签页/会话保存该图批注后，当前页面的预览仍显示旧批注，但生成任务会冻结另一套区域/保护区要求；不同图片版本本身没有混绑，缺口是同图片的批注版本。

复现步骤：A页读取同一图片v1的批注版本1；B页将保护区或修改意见更新并保存为批注版本2；A页不刷新，按显示的版本1方案点击生成。任务 payload.annotation_snapshot.version 为2，而不是A页确认的1。后端当前没有可用的 expected annotation version 输入，必然无法检测此冲突。

建议：多图预览逐格读取、展示并提交批注版本，后端事务中逐项比对；出现冲突保留方案并要求重新核对，或按已确认版本保存不可变批注快照。增加“同图同版本，批注被另一会话更新”的测试。

## 已核对的正向边界与限制

- 讨论接口只保存 conversation，不建立任务；生成经独立 production-jobs 入口。
- rewrite 任务仅对显式 refs 建立输出，候选采用检查目标 head，未选邻格不会被该路径直接保存。
- 图片修复读取明确 image_version 的批注；采用候选不会自动沿用新图片的旧坐标。
- 所有新工作流输出标注 mock，调用的是本地 demo_image，没有发现真实模型调用。
- 相同 submission_id 重放有持久化去重；问题在 UI token 生命周期和不同 token 的目标竞争。
- 未重新执行父代理已报告的全套29/10测试；独立执行了上述并发临时数据库复现。浏览器实际交互、硬件触控板手感由另一审查负责。

## 主开发修复与验证（非审查者追加结论）
- 并发首次生成：生产任务事务中检查同话格/话范围的排队与运行任务，拒绝重复占位；`test_concurrent_first_packages_do_not_duplicate_primary` 已 RED→GREEN。
- 未保存输入：统一 submitJob 边界检测所选实体本地草稿，阻止旧提示词/脚本提交；前端回归测试已 RED→GREEN。保存失败或冲突也继续保留阻止条件。
- 批注版本：前端展示并提交 annotation_versions，后端在创建任务事务内校验，变化时返回409；`test_repair_rejects_annotations_changed_since_preview` 已 RED→GREEN。
- 当前后端31项、前端11项通过。UI复查独立记录于 batch-ui-review.md。
