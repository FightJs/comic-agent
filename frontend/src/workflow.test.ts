// @vitest-environment jsdom
import { expect, it } from "vitest";
import { parseOutline, composePrompt, wheelTransform } from "./workflowLogic";
it("maps Chinese and numbered episode headings without treating chapters as episodes", () => {
  const entries = parseOutline(
    "<h2>细纲</h2><h3>第三十一话 · 归来</h3><p>内容甲</p><h3>第32话 · 相遇</h3><p>内容乙</p>",
  );
  expect(entries.map((e) => e.episode)).toEqual([31, 32]);
  expect(entries[0].text).toContain("内容甲");
  expect(parseOutline("<h2>第一章</h2>")).toEqual([]);
});
it("composes explicit prompt parts and normalizes small wheel events", () => {
  expect(
    composePrompt({ scene_prompt: "室内", content_prompt: "谈话" }),
  ).toContain("场景提示词：室内");
  expect(wheelTransform(1, 1)).toBeGreaterThan(0.99);
  expect(wheelTransform(1, 10000)).toBeGreaterThan(0.8);
});
it("blocks generation when a selected script or package still has a local draft", async () => {
  const { submitJob } = await import("./Workflow");
  const r = {
    id: "pending",
    project_id: "qa",
    version: 1,
    kind: "package",
    content: { prompt: "old" },
  } as any;
  localStorage.setItem(
    "comic-draft:qa:pending",
    JSON.stringify({ version: 1, content: { prompt: "new" } }),
  );
  try {
    await expect(submitJob("qa", "image", [r])).rejects.toThrow("未保存");
  } finally {
    localStorage.removeItem("comic-draft:qa:pending");
  }
});
it("late discussion completion clears only the submitted message, preserving new input", async () => {
  const { clearSubmittedMessage } = await import("./workflowLogic");
  expect(clearSubmittedMessage("下一条新输入", "已发送的意见")).toBe(
    "下一条新输入",
  );
  expect(clearSubmittedMessage("已发送的意见", "已发送的意见")).toBe("");
});
it("canceling an existing annotation preserves it while canceling a new one removes it", async () => {
  const { cancelAnnotationEdit } = await import("./workflowLogic");
  const original = { id: "a", note: "原意见", x: 12 },
    edited = { ...original, note: "新意见" };
  expect(cancelAnnotationEdit([edited], "a", original)).toEqual([original]);
  expect(cancelAnnotationEdit([edited], "a", null)).toEqual([]);
});
