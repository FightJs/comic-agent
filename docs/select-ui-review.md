# 自定义下拉框验收 · 2026-11-03

本轮将原有19处浏览器原生 select 替换为共用 Select；并行开发新增一处调用，最终20处。保留原选项和业务回调，统一白色面板、橄榄色活动项、选中勾号及焦点样式。弹层使用自定义 listbox 与 Popover 顶层显示，不使用浏览器原生选择菜单。支持鼠标、方向键、Home/End、Enter、Esc、Tab、前缀定位、空项禁用、长文案和280px列表滚动。

## 独立审查

审查者：`/root/ui_reviewer`，优先使用 Impeccable，独立浏览并查看截图。结论：**通过（限定本轮下拉框替换），94/100**；没有未解决阻断或重要问题。

| 项目 | 分数 | 理由 |
| --- | ---: | --- |
| 信息层级与布局 | 24/25 | 筛选与主操作层级稳定，1280/1440未见本轮下拉框引发横向溢出。 |
| 视觉协调与细节 | 24/25 | 白色菜单、橄榄色活动项、勾选、边框符合主题，深灰画布旁版本菜单清晰。 |
| 操作效率与反馈、流畅度 | 23/25 | 点击、方向键、Home/End、Enter、Esc、Tab正常，活动项自动滚动。 |
| 一致性、可访问性与边界 | 23/25 | 控件名称、ARIA状态、焦点返回、空项禁用和向上展开实测有效。 |

## 一般建议

- U1：原著版本185px窄控件中长文件名单项约5行，41项时浏览较慢。建议此类菜单可加宽至300–360px并限制视口边界。目前全文、滚动、选择均可用，不阻止交付。
- U2：资产筛选无匹配时仍沿用导入资产的空态。建议区分“暂无资产”和“没有符合当前筛选条件的资产”，后者提供清除筛选。属于既有文案问题。

## 实际检查

独立Chromium会话 `ui-review-select`，入口 `http://127.0.0.1:8765`，最终脚本 `index-DAxqU-tN.js`。

- 1280×900、1440×900，另验1280×600、1280×480。
- 原著编码和版本、脚本话号和范围、生图包范围和状态、图片版本、问题严重程度、任务状态、资产来源、模型用途。
- 抽屉选择、Esc先关列表再关抽屉、Tab关闭并移至下一控件、选择后焦点返回。
- 只读响应fixture提供41项长原著列表和空细纲；前者验证280px上限、首尾滚动和完整title，后者验证“暂无可选项”禁用及建立细纲指引。fixture已解除，没有写业务数据。
- 1280×480模型用途列表向上展开，trigger y≈359.8、menu y≈237.8、高118px，没有裁切。

截图见 `output/playwright/`：

- `select-review-long-final-1440.png`
- `select-review-drawer-final-1280.png`
- `select-review-empty-final-1280.png`
- `select-review-images-final-1280.png`
- `select-review-severity-final-1280.png`
- `select-review-package-final-1280.png`
- `select-review-package-final-1440.png`
- `select-review-up-final-1280x480.png`
- `select-review-assets-empty-1280.png`

限制：未逐一操作全部20个调用点；候选结果选择、全部业务加载/失败分支、屏幕阅读器播报、Safari/Firefox未实测。没有移动端要求，未增加手机验收。审查只读，没有部署。

## 主开发验证

最终 `npm test --prefix frontend`：6文件、18测试通过（包含下拉框4项及并行生图包测试）。`npm run build --prefix frontend`：TypeScript与Vite通过，最终hash与审查一致。`git diff --check`通过。未修改后端及真实业务数据。
