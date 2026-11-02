import { useViewState } from "./useViewState";
import { useEffect, useState } from "react";
import {
  Upload,
  Download,
  Sparkles,
  Columns2,
  Check,
  Grid2X2,
  ArrowLeft,
  History,
} from "lucide-react";
import { api, base, json, recPath, downloadZip, type RecordItem } from "./api";
import { Badge, Empty, ErrorNote, Drawer } from "./ui";
import { AnnotationCanvas } from "./AnnotationCanvas";
import { filterImages } from "./logic";
import { RecordHistory } from "./DocumentEditor";
import type { ProductionProps } from "./Production";

function ReviewImage({
  record,
  onSaved,
  refresh,
  run,
  pid,
}: ProductionProps & { record: RecordItem }) {
  const [versions, setVersions] = useState<RecordItem[]>([]),
    [selected, setSelected] = useState(record.adopted),
    [compare, setCompare] = useState(false),
    [error, setError] = useState(""),
    [history, setHistory] = useState(false),
    [instruction, setInstruction] = useState(""),
    [issue, setIssue] = useState(""),
    [severity, setSeverity] = useState("minor"),
    [characters, setCharacters] = useState(""),
    [scene, setScene] = useState("");
  const load = () =>
    api<RecordItem[]>(recPath(record) + "/versions")
      .then(setVersions)
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, [record.version, record.adopted]);
  const current = versions.find((v) => v.version === selected) || record;
  useEffect(() => {
    setCharacters(current.content.characters || "");
    setScene(current.content.scene || "");
  }, [current.version, current.id]);
  const adopt = async () => {
    try {
      onSaved(
        await api<RecordItem>(
          recPath(record) + "/adopt",
          json("POST", { version: selected }),
        ),
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const changeIssues = async (
    issues: any[],
    checked: boolean,
    metadata: Record<string, any> = {},
  ) => {
    try {
      if (current.version !== record.version)
        throw new Error("请先切换到最新版本记录问题；历史检查结果保持不变。");
      const r = await api<RecordItem>(
        recPath(record),
        json("PUT", {
          expected_version: record.version,
          content: { ...current.content, ...metadata, issues, checked },
        }),
      );
      const keepAdopted = current.version === record.adopted;
      if (keepAdopted)
        await api(
          recPath(record) + "/adopt",
          json("POST", { version: r.version }),
        );
      onSaved({ ...r, adopted: keepAdopted ? r.version : record.adopted });
      setSelected(r.version);
      setIssue("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const importVersion = async (file?: File) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("kind", "image");
    form.append("record_id", record.id);
    form.append("expected_version", String(record.version));
    try {
      const r = await api<RecordItem>(base(pid) + "/images", {
        method: "POST",
        body: form,
      });
      onSaved(r);
      setSelected(r.version);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <div className="image-header">
        <div className="actions">
          <Badge source={current.source} />
          <select
            aria-label="查看图片版本"
            value={selected}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {versions.map((v) => (
              <option key={v.version} value={v.version}>
                v{v.version} {v.version === record.adopted ? "· 当前采用" : ""}{" "}
                {v.source === "mock" ? "· 模拟" : ""}
              </option>
            ))}
          </select>
          <button onClick={() => setCompare(!compare)}>
            <Columns2 size={16} />
            {compare ? "关闭对比" : "版本对比"}
          </button>
        </div>
        <div className="actions">
          <label className="button">
            <Upload size={16} />
            导入新版本
            <input
              type="file"
              aria-label="导入图片新版本"
              className="file-input"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                void importVersion(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <button onClick={() => setHistory(true)}>
            <History size={16} />
            审核
          </button>
          <button
            className="primary"
            onClick={() => void adopt()}
            disabled={selected === record.adopted}
          >
            <Check size={16} />
            {selected === record.adopted ? "当前采用" : "采用此版本"}
          </button>
        </div>
      </div>
      <ErrorNote message={error} />
      {current.source === "mock" && (
        <div className="notice">
          当前为模拟图片，检查结论仅用于流程演示，不满足正式生产审核条件。
        </div>
      )}
      {compare ? (
        <div className="image-comparison">
          {[
            versions.find((v) => v.version === record.adopted) || record,
            current,
          ].map((v, i) => (
            <div key={i}>
              <h4>
                {i ? "正在查看" : "当前采用"} · v{v.version}
              </h4>
              <img
                src={v.content.url}
                alt={`${record.title} 版本 ${v.version}`}
              />
              <Badge source={v.source} />
              <p>{v.content.issues?.length || 0} 条对应版本问题</p>
            </div>
          ))}
        </div>
      ) : (
        <AnnotationCanvas
          key={`${current.id}-${current.version}`}
          record={current}
        />
      )}
      <div className="review-bottom">
        <section>
          <h3>本版本资料与问题</h3>
          <div className="form-grid">
            <label>
              图片人物
              <input
                value={characters}
                onChange={(e) => setCharacters(e.target.value)}
              />
            </label>
            <label>
              图片场景
              <input value={scene} onChange={(e) => setScene(e.target.value)} />
            </label>
          </div>
          <button
            disabled={current.version !== record.version}
            onClick={() =>
              void changeIssues(
                current.content.issues || [],
                !!current.content.checked,
                { characters, scene },
              )
            }
          >
            保存人物与场景
          </button>
          {!current.content.checked && (
            <div className="notice">尚未检查，不能等同于无问题。</div>
          )}
          {current.content.issues?.length
            ? current.content.issues.map((item: any, i: number) => (
                <div className="issue" key={item.id || i}>
                  <span className={`severity ${item.severity}`}>
                    {item.severity === "major"
                      ? "重大"
                      : item.severity === "general"
                        ? "一般"
                        : "轻微"}
                  </span>
                  <div>
                    <p>{item.text}</p>
                    <small>{item.basis || "人工观察"}</small>
                  </div>
                  <button
                    disabled={current.version !== record.version}
                    onClick={() =>
                      void changeIssues(
                        current.content.issues.filter(
                          (_: any, n: number) => n !== i,
                        ),
                        true,
                      )
                    }
                  >
                    标为解决
                  </button>
                </div>
              ))
            : current.content.checked && (
                <p className="muted">本版本没有记录遗留问题。</p>
              )}
          <label>
            记录人工观察
            <textarea
              aria-label="问题描述"
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
              placeholder="观察到什么，以及正确目标是什么"
            />
          </label>
          <div className="actions">
            <select
              aria-label="问题严重程度"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              <option value="minor">轻微</option>
              <option value="general">一般</option>
              <option value="major">重大</option>
            </select>
            <button
              disabled={!issue.trim() || current.version !== record.version}
              onClick={() =>
                void changeIssues(
                  [
                    ...(current.content.issues || []),
                    {
                      id: crypto.randomUUID(),
                      severity,
                      text: issue,
                      basis: "人工观察",
                    },
                  ],
                  true,
                )
              }
            >
              保存问题
            </button>
            <button
              disabled={current.version !== record.version}
              onClick={() =>
                void changeIssues(current.content.issues || [], true)
              }
            >
              记录已检查
            </button>
          </div>
        </section>
        <section>
          <h3>整体调整</h3>
          <label>
            修改要求
            <textarea
              aria-label="整体调整要求"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="描述机位、空间、站位的整体调整，或填写新的提示词"
              rows={4}
            />
          </label>
          <p className="muted">
            保留原图与历史。当前使用模拟修改及模拟复查；新版本需由你决定是否采用。
          </p>
          <button
            className="primary"
            disabled={!instruction.trim()}
            onClick={() =>
              void run("repair", record, {
                instruction,
                base_image_version: current.version,
              })
            }
          >
            <Sparkles size={16} />
            模拟修改与复查
          </button>
          <p className="muted">
            规则：先检查整体空间，再检查修改目标与保护区域；不自动追加下一轮修改。
          </p>
        </section>
      </div>
      {history && (
        <RecordHistory
          record={current}
          onSaved={onSaved}
          onClose={() => setHistory(false)}
        />
      )}
    </>
  );
}
export function Images(props: ProductionProps & { modify: boolean }) {
  const [effective, setEffective] = useState<RecordItem[]>([]),
    [query, setQuery] = useViewState(
      props.pid + ":" + props.batch + ":image-query",
      "",
    ),
    [source, setSource] = useViewState(
      props.pid + ":" + props.batch + ":image-source",
      "all",
    ),
    [status, setStatus] = useViewState(
      props.pid + ":" + props.batch + ":image-status",
      "all",
    ),
    [chosen, setChosen] = useState<string[]>([]),
    [id, setId] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [table, setTable] = useState(false);
  const images = props.records.filter(
    (r) => r.kind === "image" && r.content.batch === props.batch,
  );
  const stamp = images
    .map((r) => `${r.id}:${r.version}:${r.adopted}`)
    .join("|");
  useEffect(() => {
    let alive = true;
    Promise.all(
      images.map((r) =>
        r.adopted === r.version
          ? Promise.resolve(r)
          : api<RecordItem>(recPath(r) + `?version=${r.adopted}`),
      ),
    )
      .then((x) => {
        if (alive) setEffective(x);
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [stamp]);
  const rows = filterImages(effective, { source, query, status }).sort(
    (a, b) =>
      a.content.episode - b.content.episode ||
      a.content.panel - b.content.panel,
  );
  const [overview, setOverview] = useState(!props.modify);
  const current = overview
    ? undefined
    : images.find(
        (r) =>
          r.content.episode === props.episode &&
          r.content.panel === props.panel &&
          (r.id === id || !id),
      ) ||
      images.find(
        (r) =>
          r.content.episode === props.episode &&
          r.content.panel === props.panel,
      );
  const upload = async (file?: File) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("kind", "image");
    form.append("batch", String(props.batch));
    form.append("episode", String(props.episode));
    form.append("panel", String(Math.max(1, props.panel)));
    const existing = images.find(
      (r) =>
        r.content.episode === props.episode &&
        r.content.panel === Math.max(1, props.panel),
    );
    if (existing) {
      form.append("record_id", existing.id);
      form.append("expected_version", String(existing.version));
    }
    try {
      const r = await api<RecordItem>(base(props.pid) + "/images", {
        method: "POST",
        body: form,
      });
      props.onSaved(r);
      setId(r.id);
      setOverview(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const download = async () => {
    if (effective.some((r) => chosen.includes(r.id) && r.source === "mock"))
      setNotice("下载中包含模拟图片，不能作为真实 AI 生成成果。");
    try {
      await downloadZip(props.pid, chosen);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <div className="section-tools">
        <div className="actions">
          {current ? (
            <button
              onClick={() => {
                setId("");
                setOverview(true);
              }}
            >
              <ArrowLeft size={16} />
              返回批次速览
            </button>
          ) : (
            <>
              <input
                aria-label="搜索图片"
                placeholder="按人物、场景、文件名筛选"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <select
                aria-label="图片来源"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="all">全部来源</option>
                <option value="import">人工导入</option>
                <option value="mock">模拟</option>
              </select>
              <select
                aria-label="图片问题状态"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="all">全部状态</option>
                <option value="unreviewed">未审</option>
                <option value="major">重大遗留</option>
                <option value="general">一般问题</option>
                <option value="minor">轻微问题</option>
                <option value="clear">无遗留</option>
              </select>
            </>
          )}
        </div>
        <div className="actions">
          <label className="button">
            <Upload size={16} />
            导入本格图片
            <input
              className="file-input"
              type="file"
              aria-label="导入本格图片"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <button
            className="primary"
            onClick={() =>
              void props.run("image", undefined, {
                batch: props.batch,
                episode: props.episode,
                panel: Math.max(1, props.panel),
              })
            }
          >
            <Sparkles size={16} />
            模拟生图
          </button>
        </div>
      </div>
      <ErrorNote message={error} />
      {notice && <div className="notice">{notice}</div>}
      {current ? (
        <ReviewImage key={current.id} {...props} record={current} />
      ) : rows.length ? (
        <>
          <div className="download-bar">
            <span>
              <Grid2X2 size={16} />
              批次速览 · {rows.length} 张
            </span>
            <div className="actions">
              <button onClick={() => setTable(!table)}>
                {table ? "图片速览" : "问题总览"}
              </button>
              <button
                onClick={() =>
                  setChosen(
                    chosen.length === rows.length ? [] : rows.map((r) => r.id),
                  )
                }
              >
                {chosen.length === rows.length ? "取消全选" : "选择全部"}
              </button>
              <button disabled={!chosen.length} onClick={() => void download()}>
                <Download size={16} />
                下载选中（{chosen.length}）
              </button>
            </div>
          </div>
          {table && (
            <div className="problem-table">
              <table>
                <thead>
                  <tr>
                    <th>话格</th>
                    <th>采用版本</th>
                    <th>状态与遗留问题</th>
                    <th>来源</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button
                          onClick={() => {
                            setId(r.id);
                            props.onLocation(
                              r.content.episode,
                              r.content.panel,
                            );
                            setOverview(false);
                          }}
                        >
                          第{r.content.episode}话 · {r.content.panel}格
                        </button>
                      </td>
                      <td>v{r.version}</td>
                      <td>
                        {!r.content.checked
                          ? "未审"
                          : !r.content.issues?.length
                            ? "无遗留问题"
                            : r.content.issues.map((issue: any) => (
                                <p key={issue.id}>
                                  {issue.severity === "major"
                                    ? "重大"
                                    : issue.severity === "general"
                                      ? "一般"
                                      : "轻微"}{" "}
                                  · {issue.text}
                                </p>
                              ))}
                      </td>
                      <td>
                        <Badge source={r.source} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div
            className="image-grid"
            style={table ? { display: "none" } : undefined}
          >
            {rows.map((r) => (
              <article className="image-tile" key={r.id}>
                <label className="image-check">
                  <input
                    type="checkbox"
                    aria-label={`选择第${r.content.episode}话第${r.content.panel}格`}
                    checked={chosen.includes(r.id)}
                    onChange={(e) =>
                      setChosen(
                        e.target.checked
                          ? [...chosen, r.id]
                          : chosen.filter((x) => x !== r.id),
                      )
                    }
                  />
                </label>
                <button
                  className="image-open"
                  onClick={() => {
                    setId(r.id);
                    setOverview(false);
                    props.onLocation(r.content.episode, r.content.panel);
                    setOverview(false);
                  }}
                >
                  <img src={r.content.url} alt={r.title} />
                  <div>
                    <strong>
                      第 {r.content.episode} 话 ·{" "}
                      {String(r.content.panel).padStart(3, "0")}
                    </strong>
                    <Badge source={r.source} />
                    <span>
                      {!r.content.checked
                        ? "未审"
                        : r.content.issues?.some(
                              (i: any) => i.severity === "major",
                            )
                          ? "重大遗留"
                          : r.content.issues?.length
                            ? "需人工修改"
                            : "无遗留问题"}{" "}
                      · v{r.version}
                    </span>
                  </div>
                </button>
                <a
                  className="single-download"
                  href={r.content.url + "?download=true"}
                  download
                  onClick={() => {
                    if (r.source === "mock") setNotice("你正在下载模拟图片。");
                  }}
                >
                  <Download size={14} />
                  下载原图
                </a>
              </article>
            ))}
          </div>
        </>
      ) : (
        <Empty
          title={images.length ? "没有符合筛选条件的图片" : "让这一格成为画面"}
        >
          导入已有作品进行真实标注，或模拟生图体验版本比较和问题处理。
        </Empty>
      )}
    </>
  );
}
