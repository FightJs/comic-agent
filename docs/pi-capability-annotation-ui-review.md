# 模型能力核对与按批注编辑图片：独立定点审核

日期：2026-11-07。结论：**通过（本报告实际覆盖的两条主路径）**。无观察到的阻断或重要问题。本轮按委托不作全站评分；未覆盖的边界不估分、不宣称实页验证通过。

## 环境与方法

沿用本会话已阅读的 PRODUCT.md、DESIGN.md、交接文档与已安装 Impeccable 审核原则，补读 ModelCapabilities、ImageGeneration、Images、AnnotationCanvas 及相关公共 API。独立操作 Chrome 真实页面并查看截图，源码与 API 只辅助解释。

启动 `scripts/pi_review_server.py`，使用 `PI_REVIEW_IMAGES=1 PI_REVIEW_VISION=1`、Node 22 PATH；服务为 `http://127.0.0.1:18766/`，provider 为本机 18767，假 vault，一次性合成项目 `pi-review`。未读真实数据、真实密钥，未调用真实供应商；未修改生产或共享文件。公共 API 预置合成底图采用 v1 与批注 revision 7；实际编辑/自动保存后 revision 增至10，再并发更新至11。未把前端底图版本当作批注 revision。

实际窗口：1440×684，以及1280×800；临时 viewport 已恢复。所有页面为 SPA `/`。

## 实际验证及证据

### 模型设置 → 模型能力核对

- 折叠入口可发现，展开后显示五类：文本回复、工具调用、视觉理解、图像生成、图像编辑。初始全部未验证、无可选回执，核对保存禁用；说明只核对已有回执，不请求模型、不执行工具、不读密钥。各类 unknown 初始状态均写“供应商实测未确认；不能据此宣称真实供应商可用”。[初始页面截图](/tmp/pi-capability-annotation-ui-review/capabilities-empty.jpg)，完整五类另有实际 AX 状态观察。
- 完成下述编辑和视觉检查后，实际重开能力区域，视觉、生成、编辑有已有回执候选。实页选择图像生成与图像编辑两个完整回执，核对并保存后显示“回执已核对”“含模拟来源”，保留“不证明真实供应商可用”与不代表质量/整体能力通过的说明；显示参考数、未观察到蒙版和观察时间。未将本机替身或模拟输入称作真实供应商实测。
- 公共 API 仅把隔离图像模型标识改为 `gpt-image-fixture-changed`，随后实页点击“读取最新核对结果”，生成和编辑均显示“已过期”“模型配置已变更，原核对结果已过期”。1280下中文说明、选择控件、保存按钮可读无横向挤压。[过期状态与来源说明](/tmp/pi-capability-annotation-ui-review/capabilities-stale-1280.jpg)。

### 图片工作区 → 右侧按批注编辑图片

- 已采用 head v1 加载已保存批注。编辑区域文字后，实际 AX 显示“未保存”“区域批注尚未保存，保存完成后可生成”，按批注编辑入口禁用。批注有自动保存，截图捕获时保存可能已完成，因此不以该截图单独证明禁用瞬间。[编辑中现场截图](/tmp/pi-capability-annotation-ui-review/unsaved-disabled.jpg)。取消编辑并保存后入口恢复。
- 打开编辑面板，填写修改与保护要求，预览固定底图 v1、服务端批注 v10、保护文案、1张、固定模型与默认额外重试0。正文及提示均明确区域/保护要求为文字意图、非硬蒙版、不保证区域外像素锁定。
- 保持旧预览，公共 API 并发保存批注至v11，再实页点击“确认并生成1张”：显示“输入或当前图片已变化，尚未提交；请关闭面板并刷新资料后重新预览”。辅助 API 确认该旧任务仍为 preview、call为 prepared，未派发。[旧预览现场截图](/tmp/pi-capability-annotation-ui-review/annotation-stale.jpg)；错误文案为实际 AX 观察，截图下方超出视口，不能称截图直接显示了错误。
- 刷新项目重新打开，实页新预览固定批注v11，明确生成后本机返回真实PNG格式合成图；页面为“候选已保存”，有独立“模型视觉复查”“拒绝图片候选”“采用图片候选”。保存不等于审核通过。辅助调用回执 manifest `operation=edit`、底图v1和sha256固定、`mask=null`，status completed。[候选实际图片](/tmp/pi-capability-annotation-ui-review/edit-candidate.jpg)。
- 实际打开视觉复查，预览目标为候选图，明确“确认并检查1次”后返回模拟报告；正文称“仅用于界面与协议验收，不证明画质判断”，含固定测试问题。[视觉检查现场](/tmp/pi-capability-annotation-ui-review/vision-report.jpg)，报告完成及模拟问题以实际 AX 状态核实，截图未完整覆盖底部报告正文。
- 关闭视觉面板，仍需点击“采用图片候选”。明确人工采用后显示“已采用……另行核对模型报告与人工审核”；回工作区为v2当前采用，缩略图仍为未检查。辅助 API 确认 head=2/adopted=2、人工 reviews=[]，没有自动人审通过。

## 问题

阻断：无。重要：无。一般：本轮未发现需修复的新增问题。长面板需滚动，标题及关闭按钮保持可访问；深灰画布、缩略图与右栏沿用原视觉方向。未对无关旧界面作重新设计评价。

## 未验证及限制

- 未实页覆盖五类各自成功核对：仅生成/编辑核对，视觉候选可见；文本与工具成功核对未测。
- unknown 已核对回执的成功展示未构造；仅实页检查五类初始unknown中文边界与含模拟来源的已核对回执。另一次公共 API 创建的无参考生成也标记为含模拟来源，不将其误报为unknown成功证据。
- 未实页构造底图head在打开面板期间变化、在途晚返回、unknown图像结果不重发。也未以开发自动化冒充这些状态的独立实页验证；这些专项需以主开发对应测试证据为补充。本轮实际并发冲突验证是批注revision变化阻止提交。
- 未直接抓取网络证明具体HTTP `/images/edits` 路径；实际回执明确为edit operation，PNG返回、候选及采用已走通。非真实供应商语义编辑/画质/计费验证。
- 未覆盖屏幕阅读器、移动端、完整键盘矩阵、全部错误恢复及其他页面；不作全站评分。
- 主开发报告最终后端709通过、前端206/43文件、Node47、构建通过，属于开发辅助证据，审核员未独立重跑。

## 清理

审核服务16215已SIGINT正常退出，日志确认application shutdown complete，TemporaryDirectory正常清理，provider由finally关闭。未新增共享脚本；临时辅助脚本已清理。保留本报告和 `/tmp/pi-capability-annotation-ui-review/` 截图证据。

## 2026-11-07 补验：文本、工具、视觉成功核对与 unknown 来源

结论：**通过（本次三类能力成功核对定点补验）**。补齐前文“文本与工具成功核对未测”“unknown已核对成功展示未构造”的限制；其他未覆盖项保持原记录，不扩展为全站验收，不重新评分。

使用全新一次性合成环境、假 vault、本机18767 provider，UI仍为18766；启动选项 `PI_REVIEW_IMAGES=1 PI_REVIEW_VISION=1`。仅通过公共API创建正常任务，再独立在真实页面完成核对选择与保存；没有直接改写能力账本或工具回执。

- **文本与工具实际链路**：通过现有 Pi SDK 阶段讨论接口创建 style 会话 `34808effacdc4737a0bb79d765bb6719`，运行 `f36a90d699524778a7afef14a382fd01`。本机替身提出 `project_query` 的 catalog 查询，宿主实际执行并回传 SDK，随后得到完整文本答复。工具回执公共API实际返回 `call_id=catalog-2`、`name=project_query`、`state=matched`、`host_saved=true`、`node_status=received`，不是伪造已核对记录。能力候选中 text/tool 均来自此运行、source均unknown。
- **视觉回执**：公共API正常预览并明确start一次合成图片视觉检查，回执 `e8283df455dc43dd9c91b02b72660d58` 完成，source为mock；使用正常视觉检查fixture报告，没有手写完成记录。
- **实页操作**：Chrome打开 `http://127.0.0.1:18766/` → 合成项目 → 模型设置 → 模型能力核对，逐项选择文本回复、工具调用、视觉理解已有回执，然后点击“核对并保存结果”。三项均变为“回执已核对”，选择框归位，保存按钮禁用，显示“核对结果已保存；未请求模型或执行工具，也不表示质量或供应商整体能力通过”。
- **来源准确性**：保存后文本和工具仍明确显示“供应商实测未确认；不能据此宣称真实供应商可用”；视觉显示“含模拟来源”，说明不据此认定供应商为替身且不证明真实供应商可用，同时列“实图数：1”“语义质量未经验证”。unknown没有被改写成真实供应商已实测。
- **视觉证据**：实际1440×684下核对文本/工具两块，1280×800下核对视觉块及长中文边界，未观察到本轮新阻断、重要或一般问题。已恢复临时viewport。

证据：[文本与工具已核对且来源未确认](/tmp/pi-capability-annotation-ui-review/supplement-text-tool-1440.jpg)、[视觉已核对且语义质量未验证](/tmp/pi-capability-annotation-ui-review/supplement-vision-1280.jpg)、[辅助API最终状态与工具匹配证据](/tmp/pi-capability-annotation-ui-review/supplement-api-evidence.json)。辅助API最终核对为text/tool `verified/unknown`、vision `verified/mock`。本次新环境的generation/edit保持未验证，未重演此前已通过的生成、编辑及批注主链。

限制：以上验证真实SDK/宿主协议及页面回执核对，不证明真实供应商效果、计费或语义质量。未新增底图并发、晚返回、unknown重发等实页证据；前文这些限制保持有效。本次未改生产或共享代码，未读取真实密钥/数据，未进行付费调用。

清理：临时服务21997已正常SIGINT退出，日志确认application shutdown complete，TemporaryDirectory与provider按脚本正常清理关闭；临时辅助脚本已删除，18766/18767无监听。仅追加本节和临时证据文件。
