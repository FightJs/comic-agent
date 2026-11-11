export const toImagePoint = (
  p: { x: number; y: number },
  offset: { x: number; y: number },
  scale: number,
) => ({ x: (p.x - offset.x) / scale, y: (p.y - offset.y) / scale });
export const selectionStillValid = (
  bound: { version: number; text: string },
  version: number,
  text: string,
) => bound.version === version && bound.text === text;
export const sourceLabel = (source: string) =>
  ({ ai: "AI生成/修改", mock: "模拟", manual: "人工编辑", import: "人工导入", model: "模型抽取", original: "原著依据", adaptation: "细纲改编", asset: "资产设计" } as Record<string, string>)[source] || source;
export const filterImages = <
  T extends { source: string; content: Record<string, any> },
>(
  rows: T[],
  filters: { source: string; query: string; status: string },
) =>
  rows.filter(
    (r) =>
      (filters.source === "all" || r.source === filters.source) &&
      (!filters.query ||
        [r.content.characters, r.content.scene, r.content.filename]
          .join(" ")
          .includes(filters.query)) &&
      (filters.status === "all" ||
        (filters.status === "unreviewed"
          ? !r.content.checked
          : filters.status === "clear"
            ? r.content.checked && !r.content.issues?.length
            : r.content.issues?.some(
                (i: any) => i.severity === filters.status,
              ))),
  );
