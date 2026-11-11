// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Select } from "./Select";
afterEach(cleanup);
it("selects with keyboard, skips disabled options and returns focus", () => {
  const change = vi.fn();
  render(
    <label>
      范围
      <Select value="a" onChange={change}>
        <option value="a">当前话</option>
        <option disabled value="b">
          不可用
        </option>
        <option value="c">全项目</option>
      </Select>
    </label>,
  );
  const trigger = screen.getByRole("combobox", { name: "范围" });
  expect(document.querySelector("select")).toBeNull();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(change.mock.calls[0][0].target.value).toBe("c");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger);
});
it("dismisses without changing and blocks disabled controls", () => {
  const change = vi.fn();
  const { rerender } = render(
    <Select aria-label="来源" value="a" onChange={change}>
      <option value="a">人工</option>
    </Select>,
  );
  const trigger = screen.getByRole("combobox");
  fireEvent.click(trigger);
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(change).not.toHaveBeenCalled();
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  rerender(
    <Select aria-label="来源" disabled value="a" onChange={change}>
      <option value="a">人工</option>
    </Select>,
  );
  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});
it("keeps option text out of its label and dismisses on outside click", () => {
  render(
    <label>
      分类
      <Select value="a" onChange={() => {}}>
        <option value="a">人物</option>
        <option value="b">场景</option>
      </Select>
    </label>,
  );
  const trigger = screen.getByRole("combobox", { name: "分类" });
  fireEvent.click(trigger);
  expect(screen.getByRole("combobox", { name: "分类" })).toBe(trigger);
  expect(screen.getByRole("listbox", { hidden: true }).closest("label")).toBeNull();
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("listbox", { hidden: true })).toBeNull();
});
it("shows an explicit empty state with a disabled trigger", () => {
  render(
    <Select aria-label="资产" value="" onChange={() => {}}>
      {[]}
    </Select>,
  );
  const trigger = screen.getByRole("combobox");
  expect(trigger.textContent).toContain("暂无可选项");
  expect((trigger as HTMLButtonElement).disabled).toBe(true);
});
