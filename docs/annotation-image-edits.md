# 批注定向修图：正式调用契约

依据：原实施计划 `docs/superpowers/plans/2026-11-05-pi-integration.md` 阶段五要求修图绑定底图、批注版本、区域及保留要求，坐标文字不得当硬蒙版。本专题不扩展高级图片工作区，不引入外部脚本或另一套HTTP调用器。

## 输入与授权

沿用 `POST /api/projects/{pid}/image-jobs` 创建预览：

```json
{
  "kind": "image",
  "title": "修正眼神",
  "prompt": "修正眼神，保持原动作",
  "target": {"id": "当前底图记录ID", "version": 1},
  "annotation_edit": {"annotation_version": 2, "preserve": "保留画风及衣装"},
  "references": [],
  "submission_id": "客户端稳定操作标识",
  "max_not_sent_retries": 0
}
```

`annotation_edit` 严格拒绝未知字段；版本为非负整数（拒绝bool及字符串），`preserve`最多4000字符、默认空字符串。`prompt`保持原接口1至32000字符且不能全空白，不能只靠未保存的区域说明提交。底图必须当前版本、当前已采用且有实际图片，只接受 `kind=image`、明确 `target`、无 `basis`。历史底图不会静默升级为当前底图。附加参考沿用当前已采用且审核通过的画风/资产限制，连同第一张底图共不超过16张。

服务端按指定底图版本读取权威 `annotations` 数据，核对批注版本，冻结items及内容digest。客户端不传区域items、mask或模型配置。区域note、protect要求和preserve编译为实际发送提示词；底图始终是第一张实际图片参考。实际提示词超过32000字符拒绝预览。

预览不发送图像请求。核对底图、区域、保护意图、参考和原始费用未知状态后，沿用 `/image-jobs/{jid}/start` 明确授权。相同submission_id不能更换输入；默认额外技术重试0，只有原预览显式授权的可靠未发送尝试能重试。旧普通逐格生成仍强制生图包版本和完整prompt，不因新增编辑入口放宽。

## 冻结与候选

任务payload的 `annotation_edit` 包含输入的 `annotation_version`、`preserve`，以及服务端的 `version`、`items`、`digest`、`base_ref`。提交前核对底图当前版本、采用/审核状态、参考状态和批注版本/digest；即使批注版本不变，内容被修改也会失效。预览、排队后、每次真正网络提交前均使用既有陈旧输入检查。

复用provider冻结实际图字节/hash、保存原始返回、未知待核对和同调用恢复机制。UNKNOWN不得换标识重新发出。底图没有被修改；结果另存未采用候选，绑定 `candidate_for` 和 `input_version`，保留原话格、脚本及生图包lineage。候选内容记录 `annotation_edit` 的底图、批注版本、digest和preserve；完整区域快照可从任务payload核对。调用发出后输入变化，已付返回仍保存为 `input_stale=true` 候选，供用户明确核对，不自动采用或审核。复查可继续使用既有独立实图视觉检查入口。

批注编辑不能嵌入批次、依赖计划、自动返修计划或agent方案。该路径不使用批次自动返修专用的 `repair_of`，不借原一轮严重剧情返修授权开展其他编辑。旧 workflow/tasks 的mock修图接口仍是独立演示能力，不能用本专题结果宣称其所有讨论功能已迁移。

## 区域与蒙版边界

本入口仅把原图坐标、批注和保护要求作为文本编辑意图，明确标注“不是硬蒙版，不保证区域外像素锁定”。它不把矩形、画笔或protect JSON伪装成蒙版。

底层 `image_provider.prepare(mask=...)` 已有同尺寸、带透明区域PNG的校验和multipart发送能力，当前此接口未开放该参数，也不自动栅格化标注。替身传输验证不能证明真实供应商对蒙版或局部保留的效果。

## 验证与限制

专项：`.venv/bin/python -m pytest backend/tests/test_annotation_image_edits.py -q`，7项通过，覆盖预览/实际编辑请求、独立候选、批注digest篡改、输入严格约束、普通生图保护、未知不重发、晚返回标记过期、批次/代理scope隔离与历史底图拒绝。

本地兼容回归：专项首次4项加 `test_image_jobs.py`、`test_image_job_retries.py` 共31项通过；新增3项专项另跑共7项通过。均使用替身transport，不含真实供应商调用、真实视觉质量或独立页面验收。后续UI接线与最终验收由主任务记录。

兼容补充：`.venv/bin/python -m pytest backend/tests/test_panel_images.py backend/tests/test_image_batches.py backend/tests/test_agent_image_plans.py backend/tests/test_image_postprocess.py -q`，56项通过。最终专项7项再次通过，包含候选明确采用成功、批注过期候选拒绝采用的断言（复用workflow已有stale检查）。上述分批结果分别报告，不作为全量测试通过声明。
