# 条漫实际图片轻审核（工作台移植）

适用于实际返回图片与批准参考、明确原著片段的视觉核对。先读[工作台合同](references/workbench.md)。没有实图输入就不写已看图；不能由文字模板、成功落盘或像素尺寸推出审核通过。

默认每图一次快速剧情观察：主要人物是否明显错认，关键动作/对象、剧情结果是否缺失、相反或不可理解。只有关键剧情看不清或实际风险命中时才看必要局部/前序依据；普通格不机械逐项重审全部MEM，不新增整话跨话第二遍终审。

- 每个问题写实际看见的位置/对象、与批准证据的差异、严重程度与观察边界。只引用本次实际提供的原著片段和正确字符范围；未提供的全书事实不能当引文。估计区域不是精确分割或硬蒙版。
- 身份、画风、当前衣装、场景与动作分别比较，说明实际参考编号/版本；错误前格不能覆盖原批准依据。局部正确不等于全图正确，遮挡不可见的部分不能虚报已看清。
- 仅主要人物明显错认、关键剧情缺失/相反/不可理解时提出最多一轮必要返修建议；普通瑕疵如实记录留人工。严重问题在预算耗尽后仍保留，不能重命名PASS或删除问题以便交付。宿主未实现自动返修时只给建议，不自行生图。
- 返回宿主视觉报告schema允许的summary、issues及精确source_evidence；专项中的检查ID仅帮助描述，不添加不受支持的放行字段或伪造人工review。报告不改图片版本、人工审核或采用状态。
- 用户后续另有审核点按明确范围保留；候选采用另行操作。只在实际已采用图、原件与任务清单齐备且宿主封包验证完成时称交付完成；缺图、未知调用、未审结果不得说全批完成。不要拼接、加气泡、文字排版或改原图字节。

专项资料保留适用条件和创作依据，只核对实际命中且已观察的问题，不因规则在包内就扩大为全量检查：
- [MEM-001](rules/MEM-001.md)
- [MEM-002](rules/MEM-002.md)
- [MEM-003](rules/MEM-003.md)
- [MEM-004](rules/MEM-004.md)
- [MEM-005](rules/MEM-005.md)
- [MEM-006](rules/MEM-006.md)
- [MEM-007](rules/MEM-007.md)
- [MEM-008](rules/MEM-008.md)
- [MEM-009](rules/MEM-009.md)
- [MEM-010](rules/MEM-010.md)
- [MEM-011](rules/MEM-011.md)

## 按当前问题读取创作资料

下列资料提供具体判断，不代表新增工具或自动批准。先定位缺口再读取所需正文，不将全部细则变成每格固定检查表。

- [identity-confirmation](references/identity-confirmation.md)
- [visual-continuity](references/visual-continuity.md)
- [shot-framing](references/shot-framing.md)
- [reference-continuity](references/reference-continuity.md)
- [background-treatment](references/background-treatment.md)

- [整话画幅计划与只读检查](references/frame-ratio-plan.md)

## 按实际输入与问题读取执行资料

新资料用于具体判断，不增加工具/自动批准/强制全套检查。

- [appearance-and-single-frame](references/appearance-and-single-frame.md)
- [visual-evidence](references/visual-evidence.md)
- [light-review](references/light-review.md)
- [quality-gates](references/quality-gates.md)
- [production-decisions](references/production-decisions.md)
