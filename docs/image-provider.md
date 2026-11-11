# 图像供应商调用底座

2026-11-06状态核对：`backend/image_provider.py`为宿主调用服务，已接画风/资产单图、三套画风整组、逐格图像批次/前图依赖、实图检查与有限返修。入口见`docs/asset-image-jobs.md`、`docs/style-tests.md`、`docs/image-batches.md`和`docs/image-postprocess.md`。旧图片批注讨论及高级工作区另立专题；不能用本机替身验收宣称真实供应商质量已验证。

## 已实现的调用与存储边界

- `prepare(pid, operation_key, prompt, refs=(), mask=None, options=None, source='ai')`只登记本项目调用，不发网络。`execute(pid,id)`执行或恢复同一调用，`get(pid,id)`读取账本。参考顺序固定；无参考使用`/images/generations`，有参考使用multipart `/images/edits`。
- 从图像用途配置取得明确地址和型号，不自动换型号。执行前核对配置仍与登记一致；密钥在执行时读取钥匙串，仅用于内存请求头。启动/注册不读密钥、不发网络。
- 一次只请求1张PNG；当前支持三种标准尺寸、auto/low/medium/high质量、opaque/transparent/auto背景。未知参数明确拒绝，不把未实现的GIF/SVG/流式/高保真专属参数透传出去。模型兼容性和账户权限未实测。
- 输入最多16张项目内PNG/JPEG/WebP，每张本服务限20MiB及3200万像素。引用明确id/version，冻结文件hash、当前head/采用指针、审核与来源；执行前复查，配置/文件/版本变化不会静默提交。宿主生产关口仍须另行判断参考是否已批准。
- 硬蒙版仅接受明确上传的同尺寸PNG（小于4MiB），必须有alpha及完全透明区域，作用于第一张参考。不会把区域坐标/文字批注自动当作硬蒙版；模型遵循蒙版形状的质量仍须实际视觉检查。
- 同一项目的operation_key绑定规范化输入摘要。相同输入重复执行复用账本/结果，并发调用只有一次POST；不能用同一标识换提示词或参数。服务接入每应用共享图像容量（默认1），具体见`docs/runtime-capacity.md`；不是多进程分布式调度或全局金额/token预算。
- 成功响应先以原子写入+fsync保存脱敏JSON返回，再写PNG和项目文件登记；文件编号由调用id确定。账本完成状态与文件登记在同一事务。图片结果`checked=false`，用量缺失为null、金额始终未知；不伪造视觉通过或实际费用。
- 已知当前密钥的文字回显在响应元数据的字段名、字段值及请求编号中清理；HTTP错误正文不落盘。图片base64保持实际图像字节，不进行会损坏图片的字符串替换。不宣称覆盖所有第三方编码/图像隐写变体。
- 参考或提示词来源为模拟时，manifest与结果继承mock，宿主后续发布记录必须继续沿用。当前仅登记文件，不创建/采用style、asset或image业务记录。

## 状态与恢复

`prepared → submitting → received → completed`。

- `rejected`：明确4xx拒绝（408/409除外），保存HTTP状态及安全请求编号，不记录供应商原始错误文本，不自动重试，包括内容拒绝。
- `not_sent`：连接尚未建立等明确未提交错误。默认不重试；仅新预览中明确冻结0–4次额外尝试且有可靠逐次证据时，任务层才在原余量内继续。
- `unknown`：读/写超时、断线、5xx、重定向、异常返回或响应持久化失败，无法证明未出图，不自动重新POST。程序重启时submitting也进入unknown。没有调用新的操作标识来自动绕开未知状态。
- `received`：已保存返回但PNG或文件登记失败。再次execute只从原返回恢复，不再访问供应商；完成后复用同一文件URL。
- 落盘返回先于状态提交时，恢复会检查绑定的call_id/input_hash后完成文件登记，不能借另一个调用的返回替换。

账本表为`image_calls`；脱敏响应保存在`data/image-receipts/<call-id>.json`，实际图片在既有`data/files/`，调用结果不含密钥。磁盘完全不可写、未能持久保存返回且进程退出时，不能承诺恢复该返回，停在未知状态人工核对。画风/资产任务已有人工核对记录界面，但没有供应商结果查询接口，不把人工结论当接口验证。

## 验证与待完成

`backend/tests/test_image_provider.py`覆盖登记不请求、规范化幂等、并发一次提交、多参考顺序/真实multipart、PNG蒙版、状态/配置/文件变化、重启不重发、保存返回后登记失败恢复、错误不泄漏密钥、异常响应可追踪、项目隔离、模拟来源继承，以及真实本机HTTP供应商→已注册服务→项目文件下载。所有密钥/图片为替身/合成数据；没有真实供应商、账户、成本或生成语义实测。本轮未改前端，不新增页面视觉验收结论。

待完成：全局预算及其它故障恢复；官方账户小样与完整业务链验收。受控未发送重试接线见下节，替身验证不证明真实供应商质量。已有调用级幂等、原返回恢复、人工未知处理与候选/审核机制保留，不重复实现。

2026-11-06安全分类修复：响应已经开始后，即使读取阶段抛出ConnectError/ConnectTimeout/PoolTimeout，也记unknown并保留HTTP状态/请求编号；不能误标not_sent。该安全分类修复当时尚未接自动重试；当前仅按下节明确冻结策略处理可靠未发送证据，可能已发送错误和取消均不重发。相关测试`backend/tests/test_image_provider_retry.py`，本批证据见`docs/pi-progress.md`。

官方资料（2026-11-05实际检索并读取，型号/账户权限需另行实测）：

- [Images生成](https://developers.openai.com/api/reference/python/resources/images/methods/generate)
- [Images编辑及蒙版](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
- [图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)


## 明确未发送的有限技术重试（2026-11-06）

新单图、逐格批次及AI单图/三套画风预览可选择`max_not_sent_retries`，严格整数0–4，默认0；策略写入不可变预览/manifest及授权摘要，创建后不能扩大。业务生图和一轮剧情返修上限不变，物理网络上限为已授权图像次数×(1+额外次数)，视觉调用不参与技术重试。已有AI方案预览只能打开原任务，改策略需重新提出方案；旧记录不补造次数。

`image_attempt_grants/image_attempts/image_attempt_results`保存固定输入与授权hash、独立attempt编号/连续序号和固定枚举终结证据，不保存异常正文或密钥。只有无响应且可靠connect+ConnectError/ConnectTimeout或pool_acquire+PoolTimeout的not_sent允许下一次；响应开始、收到/拒绝、未知、未终结或旧无证据一律不重试。SDK/HTTP内部没有重试循环。

每次由任务层重新获得共享槽，提交事务中复核原版本、参考/采用/审核、配置、取消、批次暂停/时钟预算后唯一领取一次attempt。取消保留在途返回；重启只记中断，需用户明确恢复且不重置余量。只恢复原返回`restore_only`不得新建attempt。依赖改绑仅在未提交时进行；独立已授权返修继承同策略，不改原图账本。页面显示逐次证据和剩余次数，历史缺字段明确未知，结果仍须人工采用及审核。

本机替身自动化与独立UI证据见`docs/pi-progress.md`、`docs/pi-technical-retry-ui-review.md`（最终结论以报告为准）；未使用真实供应商。
