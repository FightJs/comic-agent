// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useDraft } from "./useDraft";
import type { RecordItem } from "./api";
const original: RecordItem = {
  id: "doc",
  project_id: "project",
  kind: "outline",
  title: "细纲",
  version: 1,
  adopted: 1,
  source: "manual",
  review: "pending",
  created: "",
  updated: "",
  content: { html: "旧文" },
};
beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("dirty draft survives unmount and mock lineage is restored", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "离线" }), { status: 503 }),
    );
  const first = renderHook(() => useDraft(original, () => {}));
  act(() => {
    first.result.current.markMock();
    first.result.current.setContent({ html: "修改中的模拟文本" });
  });
  first.unmount();
  const second = renderHook(() => useDraft(original, () => {}));
  expect(second.result.current.content.html).toBe("修改中的模拟文本");
  await act(async () => {
    await second.result.current.save();
  });
  expect(fetcher.mock.calls[0][0]).toContain("/mock-edit");
  expect(second.result.current.error).toContain("离线");
  expect(second.result.current.content.html).toBe("修改中的模拟文本");
});
it("late server refresh updates clean draft but never overwrites dirty text", () => {
  const { result, rerender } = renderHook(
    ({ record }) => useDraft(record, () => {}),
    { initialProps: { record: original } },
  );
  rerender({
    record: { ...original, version: 2, content: { html: "模型返回" } },
  });
  expect(result.current.content.html).toBe("模型返回");
  act(() => result.current.setContent({ html: "正在编辑" }));
  rerender({
    record: { ...original, version: 3, content: { html: "迟到内容" } },
  });
  expect(result.current.content.html).toBe("正在编辑");
});
it("edits during a slow save are saved in a following version", async () => {
  let finish!: (r: Response) => void;
  let calls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    calls++;
    const body = JSON.parse(options!.body as string);
    if (calls === 1)
      return new Promise<Response>((r) => {
        finish = r;
      });
    return new Response(
      JSON.stringify({ ...original, version: 3, content: body.content }),
      { status: 200 },
    );
  });
  const { result } = renderHook(() => useDraft(original, () => {}));
  act(() => result.current.setContent({ html: "第一次" }));
  let saving: Promise<void>;
  act(() => {
    saving = result.current.save();
  });
  act(() => result.current.setContent({ html: "保存途中继续编辑" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  await act(async () => {
    finish(
      new Response(
        JSON.stringify({
          ...original,
          version: 2,
          content: { html: "第一次" },
        }),
        { status: 200 },
      ),
    );
    await saving;
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(40);
  });
  expect(result.current.content.html).toBe("保存途中继续编辑");
  expect(result.current.head.current.version).toBe(3);
  expect(result.current.status).toBe("已保存");
});
it('failed conflict refresh keeps local edits and reports the failure',async()=>{
 vi.spyOn(globalThis,'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
 const {result}=renderHook(()=>useDraft(original,()=>{}));
 act(()=>result.current.setContent({html:'不可丢失的本地编辑'}));
 await act(async()=>{await expect(result.current.resolve()).resolves.toBeUndefined()});
 expect(result.current.content.html).toBe('不可丢失的本地编辑');
 expect(result.current.head.current.version).toBe(1);
 expect(result.current.error).toContain('无法读取');
});
it('explicit discard reads latest without a write and clears the conflict and cached draft',async()=>{
 let puts=0;
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async(_url,options)=>{
  if(options?.method==='PUT'){
   puts++;if(puts===1)return new Response(JSON.stringify({detail:'版本冲突'}),{status:409});
   const body=JSON.parse(options.body as string);return new Response(JSON.stringify({...original,version:3,content:body.content}));
  }
  return new Response(JSON.stringify({...original,version:2,content:{html:'服务器新内容'}}));
 });
 const onSaved=vi.fn(),{result}=renderHook(()=>useDraft(original,onSaved));
 act(()=>result.current.setContent({html:'冲突草稿'}));
 await act(async()=>{await result.current.save()});expect(result.current.error).toContain('版本冲突');
 await act(async()=>{await result.current.discard()});
 expect(result.current.content.html).toBe('服务器新内容');expect(result.current.dirty).toBe(false);expect(result.current.error).toBe('');
 expect(localStorage.getItem('comic-draft:project:doc')).toBeNull();expect(puts).toBe(1);
 act(()=>result.current.setContent({html:'重新编辑'}));await act(async()=>{await result.current.save()});
 const body=JSON.parse(fetcher.mock.calls.at(-1)![1]!.body as string);expect(body.expected_version).toBe(2);expect(result.current.status).toBe('已保存');
});
it('failed discard keeps the draft and original version',async()=>{
 vi.spyOn(globalThis,'fetch').mockRejectedValue(new TypeError('offline'));
 const {result}=renderHook(()=>useDraft(original,()=>{}));act(()=>result.current.setContent({html:'不可丢失'}));
 await act(async()=>{await result.current.discard()});
 expect(result.current.content.html).toBe('不可丢失');expect(result.current.head.current.version).toBe(1);
 expect(localStorage.getItem('comic-draft:project:doc')).toContain('不可丢失');expect(result.current.error).toContain('草稿');
});
it('editing while discard is loading prevents it from replacing newer local text',async()=>{
 let finish!:(r:Response)=>void;
 vi.spyOn(globalThis,'fetch').mockImplementation(()=>new Promise<Response>(resolve=>{finish=resolve}));
 const onSaved=vi.fn(),{result}=renderHook(()=>useDraft(original,onSaved));
 act(()=>result.current.setContent({html:'原草稿'}));let discarding!:Promise<void>;
 act(()=>{discarding=result.current.discard()});act(()=>result.current.setContent({html:'读取途中继续写'}));
 await act(async()=>{finish(new Response(JSON.stringify({...original,version:2,content:{html:'服务器'}})));await discarding});
 expect(result.current.content.html).toBe('读取途中继续写');expect(result.current.head.current.version).toBe(1);expect(onSaved).not.toHaveBeenCalled();
 expect(localStorage.getItem('comic-draft:project:doc')).toContain('读取途中继续写');expect(result.current.error).toContain('编辑');
});
it('discard finishing after unmount cannot erase another editor cache',async()=>{
 let finish!:(r:Response)=>void;vi.spyOn(globalThis,'fetch').mockImplementation(()=>new Promise<Response>(resolve=>{finish=resolve}));
 const onSaved=vi.fn(),{result,unmount}=renderHook(()=>useDraft(original,onSaved));
 act(()=>result.current.setContent({html:'旧窗口草稿'}));let discarding!:Promise<void>;
 act(()=>{discarding=result.current.discard()});unmount();
 localStorage.setItem('comic-draft:project:doc','新窗口自己的草稿');
 await act(async()=>{finish(new Response(JSON.stringify({...original,version:2})));await discarding});
 expect(localStorage.getItem('comic-draft:project:doc')).toBe('新窗口自己的草稿');expect(onSaved).not.toHaveBeenCalled();
});
