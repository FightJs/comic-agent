export const preparationTabs = {
  original: [["original", "小说原著"], ["memory", "理解与关系"]],
  skeleton: [["skeleton", "改编骨架"], ["outline", "分集细纲"]],
  style: [["style", "三版画风比较"], ["asset", "全面资产生成与确认"]],
} as const;
export function preparationGroup(stage: string): keyof typeof preparationTabs {
  if (stage === "skeleton" || stage === "outline") return "skeleton";
  if (stage === "style" || stage === "asset") return "style";
  return "original";
}
