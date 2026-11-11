# 五类模型能力回执核对

本功能按原 Pi 集成计划“模型能力检查，分别记录文本、工具、视觉、生成、编辑的验证结果”补齐记录入口。采用已有成功业务回执作为检查样本，不增设主动付费探测器。不因配置保存、模型能力声明或记录 `source=ai` 就宣称供应商已实测。

## 接口和权限

- `GET /api/projects/{pid}/model-capabilities`：只读返回 `capabilities` 五项，以及本项目每类最多近期20项 `candidates`。候选不是已验证结果；不返回正文、提示词、原始供应商返回、服务地址或密钥。
- `POST /api/projects/{pid}/model-capabilities/reconcile`：`{"evidence":[{"kind":"text","receipt_id":"已有运行编号"}]}`。类别为 `text/tool/vision/generation/edit`，每次1–20项，拒绝额外字段。仅核对指定本项目既有完整回执并登记证据，不读取钥匙串，不执行模型、业务工具、图片或视觉调用。任一项不存在或不合规时整批不登记。
- 工具核对唯一运行层操作是已有 `checkpoint_details`，读取原运行检查点；不是重新调用模型或工具。运行层不可用、原回执缺失、分支归属或输入/结果摘要不匹配时，保持未验证，不恢复、不重发。

返回项为 `kind/status/source/profile_hash/observed_at/receipt/limits/reason_codes`。`status` 为 `unverified/verified/stale`；`verified` 只表示该回执所覆盖的协议行为有证据。`receipt` 是 `{type,id}`，没有原文。`observed_at` 来自原回执更新时间，不伪装成新供应商运行时间。数据库单独记录本次核对时间，重复相同核对不新增记录。

## 五类证据与复用服务

| 类别 | 既有来源与判据 | 不能证明的事情 |
| --- | --- | --- |
| text | `agent_runs` 完成且有完整回复；`agent_requests.config` 固定公开配置 | 长篇理解、回复语义质量、费用 |
| tool | 上述运行，另以 `tool_receipts.summaries/compare` 对账 `PiRuntime.request('checkpoint_details')`；至少一个工具具备模型调用身份、宿主结果、SDK接收与相同输入/结果摘要 | 只允许工具、只保存宿主结果、仅运行完成均不足；不证明全部工具类型可用 |
| vision | `vision_reviews` 完成，manifest含固定图片文件和SHA；重用 `validate_report` 复验原返回且与已存结构报告相同 | 看图语义质量、人工审核通过、当前图仍与旧检查一致 |
| generation | `image_calls` 完成、operation=generate、无参考/蒙版、已登记PNG输出与尺寸/SHA | 多参考、编辑、蒙版或画质 |
| edit | `image_calls` 完成、operation=edit、固定底图文件与SHA、已登记PNG输出；记录本次 reference_count/mask_observed | 没用过的参考数量/参数、蒙版视觉效果、保留区域准确性 |

图像样本来自现有 `ImageProvider.prepare/execute/get`；视觉样本来自 `VisionReviews.prepare/execute/get`；文本/工具来自现有讨论运行。这些服务仍各自保留原授权、容量、调用账本、原返回恢复、未知不重发等规则，本模块不绕过它们。想补缺项时，进入原业务页面，在原输入预览和明确授权之后产生样本，再回来核对。当前版本不列生产文本/图谱运行作为候选，不因此称那些业务未实现。

## 配置、来源与限制

公开 profile hash 包括用途、规范化服务地址、型号及协议，不含密钥。文本/工具绑定text配置；视觉绑定vision；生成/编辑绑定image。更改公开配置后原记录显示 `stale`，不能继续显示当前配置已验证；缺少记录显示未验证。它不是密钥有效性检查：仅更换密钥不改变公开profile hash，后续原业务是否成功仍以新任务回执为准。

来源 `mock` 仅表示manifest明确含模拟来源，不能据此断言供应商是替身，含模拟输入也可能经过真实付费调用；其他一律 `unknown`。本机loopback地址可能是真实Ollama或兼容代理，远程地址同样不足以证明真实供应商身份，`ai` 也只是资料来源，所以本功能不会自动生成 `real`。界面须将mock展示为“含模拟来源”，unknown展示为“回执核对”；二者都不能写“真实供应商验收通过”。本模块不计算新费用，既有费用未知仍未知，不读取图片字节再做像素SHA复验，不以旧业务成功保证当前服务或账户可用。

独立主动小样并非原计划规定的唯一检查方式。上述逐类显式对账可以形成最小可核对实现；供应商实际效果仍需另行授权业务样本与人工验收，不能从本表推导。

## 验证

定向命令：`.venv/bin/python -m pytest backend/tests/test_model_capabilities.py -q`。测试仅临时SQLite、合成回执和只读运行层替身，涵盖五类分离、未完成/未知拦截、配置过期、项目隔离、严格输入、来源保守、工具完整往返、原始视觉报告一致、候选上限、幂等及批量登记原子性。不调用真实供应商或真实钥匙串。全量与独立页面证据由本轮集成记录单列，本文件不冒称已完成这些验收。
