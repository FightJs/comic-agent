import { Fragment, useState, useRef, useEffect } from "react";
import { sourceLabel } from "./logic";
import type { RecordItem } from "./api";
import "./package-table.css";
export function PackageTable({
  rows,
  records,
  selected,
  setSelected,
  open,
  compare,
  storageKey,
}: {
  storageKey?: string;
  rows: RecordItem[];
  records: RecordItem[];
  selected: string[];
  setSelected: (ids: string[]) => void;
  open: (r: RecordItem) => void;
  compare: (r: RecordItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!storageKey) return;
    try {
      const v = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (v && scroll.current) {
        scroll.current.scrollTop = v.top;
        scroll.current.scrollLeft = v.left;
      }
    } catch {}
  }, [storageKey]);
  const toggle = (ids: string[], checked: boolean) =>
    setSelected(
      checked
        ? [...new Set([...selected, ...ids])]
        : selected.filter((id) => !ids.includes(id)),
    );
  const assets = (r: RecordItem, category: string) => {
    const refs = (r.content.references || []).filter((ref: any) => {
      const asset = records.find((a) => a.id === ref.id);
      return category === "人物"
        ? asset?.content.category === "人物"
        : asset?.content.category !== "人物";
    });
    return refs.length ? (
      refs.map((ref: any) => (
        <div className="package-ref" key={ref.id}>
          <strong>
            {records.find((a) => a.id === ref.id)?.title || "历史参考"}
          </strong>
          <small>
            v{ref.version} · {ref.purpose || "未标用途"}
          </small>
        </div>
      ))
    ) : (
      <span className="muted">未绑定</span>
    );
  };
  const candidates = (r: RecordItem) =>
    records.filter(
      (x) => x.content.candidate_for === r.id && !x.content.adopted_into && !x.content.rejected,
    ).length;
  const stale = (r: RecordItem) =>
    records.some(
      (s) =>
        s.id === r.content.script_id && s.version !== r.content.script_version,
    );
  return (
    <section className="package-table-section">
      <div className="table-guidance">
        <span>
          共 {new Set(rows.map((r) => r.content.episode)).size} 话 ·{" "}
          {rows.length} 格 · 表头和话格固定，横向滚动查看提示词
        </span>
        <button onClick={() => setExpanded(!expanded)}>
          {expanded ? "收起长文本" : "展开长文本"}
        </button>
      </div>
      <div
        ref={scroll}
        onScroll={(e) => {
          if (storageKey)
            localStorage.setItem(
              storageKey,
              JSON.stringify({
                top: e.currentTarget.scrollTop,
                left: e.currentTarget.scrollLeft,
              }),
            );
        }}
        className={"package-table-scroll" + (expanded ? " expanded" : "")}
      >
        <table className="package-table">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  aria-label="选择当前显示全部生图包"
                  checked={
                    rows.length > 0 &&
                    rows.every((r) => selected.includes(r.id))
                  }
                  onChange={(e) =>
                    toggle(
                      rows.map((r) => r.id),
                      e.target.checked,
                    )
                  }
                />
              </th>
              <th>话 / 格</th>
              <th>状态与操作</th>
              <th>人物资产</th>
              <th>场景 / 其他资产</th>
              <th>场景提示词</th>
              <th>内容提示词</th>
              <th>站位提示词</th>
              <th>分镜</th>
              <th>完整提示词</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const episodeRows = rows.filter(
                  (x) => x.content.episode === r.content.episode,
                ),
                count = candidates(r);
              return (
                <Fragment key={r.id}>
                  {(!i ||
                    rows[i - 1].content.episode !== r.content.episode) && (
                    <tr className="package-episode">
                      <th colSpan={10}>
                        <label>
                          <input
                            type="checkbox"
                            aria-label={`选择第${r.content.episode}话显示的${episodeRows.length}格`}
                            checked={episodeRows.every((x) =>
                              selected.includes(x.id),
                            )}
                            onChange={(e) =>
                              toggle(
                                episodeRows.map((x) => x.id),
                                e.target.checked,
                              )
                            }
                          />
                          第 {r.content.episode} 话{" "}
                          <span>{episodeRows.length} 格</span>
                        </label>
                      </th>
                    </tr>
                  )}
                  <tr className={selected.includes(r.id) ? "selected" : ""}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`选择第${r.content.episode}话第${r.content.panel}格`}
                        checked={selected.includes(r.id)}
                        onChange={(e) => toggle([r.id], e.target.checked)}
                      />
                    </td>
                    <th scope="row">
                      <button
                        data-package-open={r.id}
                        aria-label={`查看第${r.content.episode}话第${r.content.panel}格生图包`}
                        onClick={() => open(r)}
                      >
                        {r.content.episode}话 /{" "}
                        {String(r.content.panel).padStart(2, "0")}格
                      </button>
                      <small>v{r.version}</small>
                    </th>
                    <td>
                      <span
                        className={
                          !r.content.prompt?.trim() || stale(r)
                            ? "package-warning"
                            : ""
                        }
                      >
                        {!r.content.prompt?.trim()
                          ? "缺少提示词"
                          : stale(r)
                            ? "脚本已更新"
                            : "提示词已备"}
                      </span>
                      <small>
                        {sourceLabel(r.source)} · 脚本 v
                        {r.content.script_version || "未绑定"}
                      </small>
                          {count > 0 && (
                        <button onClick={() => compare(r)}>
                          比较候选 {count}
                        </button>
                      )}
                    </td>
                    <td>{assets(r, "人物")}</td>
                    <td>{assets(r, "其他")}</td>
                    {[
                      "scene_prompt",
                      "content_prompt",
                      "position_prompt",
                      "shot_prompt",
                      "prompt",
                    ].map((k) => (
                      <td key={k}>
                        <div className="package-cell-text">
                          {r.content[k] ||
                            (k === "scene_prompt"
                              ? r.content.scene
                              : k === "shot_prompt"
                                ? r.content.camera
                                : "") ||
                            "未拆分 / 未填写"}
                        </div>
                      </td>
                    ))}
                  </tr>
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
