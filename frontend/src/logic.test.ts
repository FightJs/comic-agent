import { describe, it, expect } from "vitest";
import {
  toImagePoint,
  selectionStillValid,
  sourceLabel,
  filterImages,
} from "./logic";
describe("原图坐标与迟到回复保护", () => {
  it("缩放平移之后返回原图坐标", () => {
    expect(toImagePoint({ x: 180, y: 140 }, { x: 20, y: 40 }, 2)).toEqual({
      x: 80,
      y: 50,
    });
  });
  it("已改选区和新版本均不自动覆盖", () => {
    expect(selectionStillValid({ version: 2, text: "原文" }, 2, "原文")).toBe(
      true,
    );
    expect(selectionStillValid({ version: 2, text: "原文" }, 3, "原文")).toBe(
      false,
    );
    expect(selectionStillValid({ version: 2, text: "原文" }, 2, "新文")).toBe(
      false,
    );
  });
  it("模拟来源有明确文案且筛选依据采用版本", () => {
    expect(sourceLabel("mock")).toBe("模拟");
    const rows: any[] = [
      {
        id: "a",
        source: "mock",
        content: {
          characters: "阿青",
          scene: "院落",
          issues: [{ severity: "major" }],
        },
      },
      {
        id: "b",
        source: "manual",
        content: { characters: "阿青", scene: "山林", issues: [] },
      },
    ];
    expect(
      filterImages(rows, {
        source: "manual",
        query: "阿青",
        status: "all",
      }).map((x) => x.id),
    ).toEqual(["b"]);
    expect(
      filterImages(rows, { source: "all", query: "", status: "major" }).map(
        (x) => x.id,
      ),
    ).toEqual(["a"]);
  });
});
