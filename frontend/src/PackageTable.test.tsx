// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { RecordItem } from "./api";
import { PackageTable } from "./PackageTable";
afterEach(cleanup);
it("reviews 150 panels across five episodes and selects an episode without changing panel identity", () => {
  const rows = Array.from({ length: 150 }, (_, i) => ({
    id: `p${i}`,
    kind: "package",
    version: 1,
    content: {
      episode: 31 + Math.floor(i / 30),
      panel: (i % 30) + 1,
      prompt: "完整提示词",
      scene_prompt: "雨夜街道",
      references: [],
    },
  })) as any[];
  const select = vi.fn(),
    open = vi.fn();
  render(
    <PackageTable
      rows={rows}
      records={rows}
      selected={[]}
      setSelected={select}
      open={open}
      compare={() => {}}
    />,
  );
  expect(screen.getAllByRole("row")).toHaveLength(156);
  fireEvent.click(
    screen.getByRole("checkbox", { name: "选择第33话显示的30格" }),
  );
  expect(select).toHaveBeenLastCalledWith(rows.slice(60, 90).map((r) => r.id));
  fireEvent.click(
    screen.getByRole("button", { name: "查看第35话第30格生图包" }),
  );
  expect(open).toHaveBeenCalledWith(rows[149]);
  expect(screen.getByRole("columnheader", { name: "站位提示词" })).toBeTruthy();
});

it('labels AI-edited packages with their actual source',()=>{
  const r:RecordItem={id:'ai-package',project_id:'p',kind:'package',title:'AI生图包',version:2,adopted:2,source:'ai',review:'pending',created:'',updated:'',content:{episode:1,panel:1,batch:1,prompt:'新提示'}};
  render(<PackageTable rows={[r]} records={[r]} selected={[]} setSelected={()=>{}} open={()=>{}} compare={()=>{}}/>);
  expect(screen.getByText(/AI生成\/修改/)).toBeTruthy();
  expect(screen.queryByText(/人工内容/)).toBeNull();
});
