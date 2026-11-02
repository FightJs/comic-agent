import { useEffect, useState } from "react";
import { api, base, json, recPath, downloadZip, RecordItem } from "./api";
import { AnnotationCanvas, Annotation } from "./AnnotationCanvas";
import { CandidateReview, Conversation } from "./Workflow";
import { primaryRecord } from "./workflowLogic";
import { useViewState } from "./useViewState";
import { Badge, Drawer, Empty, ErrorNote } from "./ui";
import { RecordHistory } from "./DocumentEditor";
import type { ProductionProps } from "./Production";
export function Images(props: ProductionProps & { modify?: boolean }) {
  const { pid, records, episode, panel } = props;
  const heads = records.filter((r) => r.kind === "image" && primaryRecord(r));
  const [effective, setEffective] = useState<RecordItem[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [query, setQuery] = useViewState(pid + ":images:query", ""),
    [filter, setFilter] = useViewState(pid + ":images:filter", "all"),
    [scope, setScope] = useViewState(pid + ":images:scope", "batch"),
    [view, setView] = useState<RecordItem | null>(null),
    [versions, setVersions] = useState<RecordItem[]>([]),
    [compare, setCompare] = useState(false),
    [candidate, setCandidate] = useState<RecordItem | null>(null),
    [error, setError] = useState(""),
    [history, setHistory] = useState(false),
    [details, setDetails] = useState(false),
    [hideRail, setHideRail] = useState(false),
    [hideChat, setHideChat] = useState(false),
    [annotations, setAnnotations] = useState<Annotation[]>([]),
    [saved, setSaved] = useState(false),
    [annotationRevision, setAnnotationRevision] = useState(0),
    [focusAnnotation, setFocusAnnotation] = useState("");
  const signature = heads
    .map((r) => r.id + ":" + r.version + ":" + r.adopted)
    .join(",");
  useEffect(() => {
    let active = true;
    Promise.all(
      heads.map((r) => api<RecordItem>(recPath(r) + "?version=" + r.adopted)),
    )
      .then((r) => {
        if (active) setEffective(r);
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
    };
  }, [signature]);
  const visible = effective.filter(
    (r) =>
      (scope === "all" || scope === "episode"
        ? scope === "all" || r.content.episode === episode
        : r.content.batch === props.batch) &&
      (!query ||
        [
          r.content.characters,
          r.content.scene,
          r.title,
          String(r.content.panel),
        ]
          .join(" ")
          .includes(query)) &&
      (filter === "all" || filter === "unchecked"
        ? !r.content.checked || filter === "all"
        : (r.content.issues || []).some(
            (x: any) => filter === "issues" || x.severity === filter,
          )),
  );
  const active =
    visible.find(
      (r) => r.content.episode === episode && r.content.panel === panel,
    ) || visible[0];
  const head = heads.find((r) => r.id === active?.id);
  useEffect(() => {
    if (
      active &&
      (active.content.episode !== episode || active.content.panel !== panel)
    )
      props.onLocation(active.content.episode, active.content.panel);
  }, [active?.id, episode, panel]);
  useEffect(() => {
    if (!active) {
      setView(null);
      return;
    }
    let alive = true;
    setView(active);
    setSaved(false);
    setAnnotations([]);
    api<RecordItem[]>(recPath(active) + "/versions")
      .then((r) => {
        if (alive) setVersions(r);
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [active?.id, active?.version, head?.version]);
  const picked = effective.filter((r) => selected.includes(r.id));
  const refs = picked.length
    ? picked.map((r) => (r.id === view?.id ? view : r))
    : view
      ? [view]
      : [];
  const candidates = (r: RecordItem) =>
    records.filter(
      (x) => x.content.candidate_for === r.id && !x.content.adopted_into,
    );
  const importImage = async (file?: File, asVersion = false) => {
    if (!file) return;
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("kind", "image");
      data.append("batch", String(props.batch));
      data.append("episode", String(episode));
      data.append("panel", String(panel));
      if (asVersion && head) {
        data.append("record_id", head.id);
        data.append("expected_version", String(head.version));
      }
      props.onSaved(
        await api(base(pid) + "/images", { method: "POST", body: data }),
      );
      await props.refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const adoption = async () => {
    if (!view) return;
    try {
      props.onSaved(
        await api(
          recPath(view) + "/adopt",
          json("POST", { version: view.version }),
        ),
      );
      await props.refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div
      className={
        "image-studio" +
        (hideRail ? " rail-hidden" : "") +
        (hideChat ? " chat-hidden" : "")
      }
    >
      <div className="studio-toolbar">
        <div className="actions">
          <button onClick={() => setHideRail(!hideRail)}>
            {hideRail ? "显示缩略图" : "收起缩略图"}
          </button>
          <button onClick={() => setHideChat(!hideChat)}>
            {hideChat ? "显示批注对话" : "专注画布"}
          </button>
          <select
            aria-label="图片显示范围"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="batch">当前10话</option>
            <option value="episode">当前话</option>
            <option value="all">全部话</option>
          </select>
        </div>
        <div className="actions">
          <span>
            {selected.length
              ? `已选 ${selected.length} 张`
              : "点击图片审核，勾选多图共同修改"}
          </span>
          {selected.length > 0 && (
            <>
              <button onClick={() => setSelected([])}>清空</button>
              <button
                onClick={() =>
                  void downloadZip(pid, selected).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                下载选中原图
              </button>
            </>
          )}
          <label className="button">
            导入本格图片
            <input
              className="file-input"
              type="file"
              aria-label="导入本格图片"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                void importImage(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>
      <ErrorNote message={error} />
      <div className="studio-columns">
        {!hideRail && (
          <aside className="thumbnail-rail">
            <input
              placeholder="查找人物、场景、格号"
              aria-label="查找图片"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              aria-label="问题筛选"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">全部图片</option>
              <option value="unchecked">未检查</option>
              <option value="issues">有问题</option>
              <option value="major">重大问题</option>
              <option value="general">一般问题</option>
              <option value="minor">轻微问题</option>
            </select>
            <label className="select-visible">
              <input
                type="checkbox"
                checked={
                  visible.length > 0 &&
                  visible.every((r) => selected.includes(r.id))
                }
                onChange={(e) =>
                  setSelected(e.target.checked ? visible.map((r) => r.id) : [])
                }
              />
              选择当前显示 {visible.length} 张
            </label>
            {visible.map((r) => (
              <article
                className={active?.id === r.id ? "active" : ""}
                key={r.id}
              >
                <div className="thumb-caption">
                  <input
                    type="checkbox"
                    aria-label={`选择图片${r.content.episode}话${r.content.panel}格`}
                    checked={selected.includes(r.id)}
                    onChange={() =>
                      setSelected((s) =>
                        s.includes(r.id)
                          ? s.filter((x) => x !== r.id)
                          : [...s, r.id],
                      )
                    }
                  />
                  <strong>
                    {r.content.episode}话 · {r.content.panel}格
                  </strong>
                  <small>v{r.version}</small>
                </div>
                <button
                  className="thumbnail-button"
                  onClick={() =>
                    props.onLocation(r.content.episode, r.content.panel)
                  }
                >
                  <img
                    src={r.content.url}
                    alt={`第${r.content.episode}话第${r.content.panel}格`}
                  />
                </button>
                <small>
                  {r.content.checked
                    ? (r.content.issues?.length || 0) + "条问题"
                    : "未检查"}{" "}
                  · {r.source === "mock" ? "模拟图片" : "人工导入"}
                </small>
                {candidates(r).length > 0 && (
                  <button
                    className="candidate-link"
                    onClick={() => setCandidate(r)}
                  >
                    比较修改结果 · {candidates(r).length}
                  </button>
                )}
              </article>
            ))}
            {!visible.length && <p>没有匹配图片</p>}
          </aside>
        )}
        <section className="studio-canvas">
          {view && head ? (
            <>
              <div className="canvas-version-bar">
                <strong>
                  第{view.content.episode}话 · 第{view.content.panel}格
                </strong>
                <select
                  aria-label="查看图片版本"
                  value={view.version}
                  onChange={(e) => {
                    setView(
                      versions.find((r) => r.version === +e.target.value) ||
                        view,
                    );
                    setSaved(false);
                    setAnnotations([]);
                  }}
                >
                  {versions.map((r) => (
                    <option value={r.version} key={r.version}>
                      v{r.version}
                      {r.version === head.adopted ? " · 当前采用" : ""}
                    </option>
                  ))}
                </select>
                <button onClick={() => setCompare(!compare)}>
                  {compare ? "返回画布" : "新旧对比"}
                </button>
                <button
                  disabled={view.version === head.adopted}
                  onClick={() => void adoption()}
                >
                  {view.version === head.adopted ? "当前采用" : "采用此版本"}
                </button>
                <button onClick={() => setDetails(true)}>资料与问题</button>
              </div>
              {view.source === "mock" && (
                <div className="mock-ribbon">
                  模拟图片 · 用于验证流程，未执行真实 AI 修改
                </div>
              )}
              {compare ? (
                <div className="candidate-images">
                  {[active!, view].map((r, i) => (
                    <figure key={i}>
                      <img
                        src={r.content.url}
                        alt={i ? "正在查看" : "当前采用"}
                      />
                      <figcaption>
                        {i ? "正在查看" : "当前采用"} · v{r.version}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              ) : (
                <AnnotationCanvas
                  key={view.id + ":" + view.version}
                  record={view}
                  focusAnnotation={focusAnnotation}
                  onState={(a, s, revision) => {
                    setAnnotationRevision(revision);
                    setAnnotations(a);
                    setSaved(s);
                  }}
                />
              )}
              <div className="actions">
                <a
                  className="button"
                  download
                  href={view.content.url + "?download=true"}
                >
                  下载当前原图
                </a>
                <label className="button">
                  导入新版本
                  <input
                    className="file-input"
                    aria-label="导入图片新版本"
                    type="file"
                    accept="image/png,image/jpeg"
                    onChange={(e) => {
                      void importImage(e.target.files?.[0], true);
                      e.target.value = "";
                    }}
                  />
                </label>
                <button onClick={() => setHistory(true)}>审核与历史</button>
                {candidates(head).length > 0 && (
                  <button
                    className="primary"
                    onClick={() => setCandidate(head)}
                  >
                    比较候选并采用
                  </button>
                )}
              </div>
            </>
          ) : (
            <Empty title="图片工作区">
              先在生图包选择话格生成图片，或导入当前格图片。筛选无结果时可调整范围。
            </Empty>
          )}
        </section>
        {!hideChat && (
          <aside className="studio-discussion">
            {view && (
              <section className="region-summary">
                <h3>
                  当前底图区域批注 <small>v{view.version}</small>
                </h3>
                {annotations.length ? (
                  annotations.map((a, i) => (
                    <button
                      className="region-summary-item"
                      key={a.id}
                      onClick={() =>
                        setFocusAnnotation(a.id + ":" + Date.now())
                      }
                    >
                      <strong>
                        {i + 1} · {a.type === "protect" ? "保护区" : "修改区域"}
                      </strong>
                      <p>{a.note || "待填写建议"}</p>
                    </button>
                  ))
                ) : (
                  <p className="muted">
                    在画面上点选或框选区域，输入修改建议。
                  </p>
                )}
                <small>
                  {saved ? "区域批注已保存" : "区域批注读取或保存中"}
                </small>
              </section>
            )}
            {refs.length > 0 && (
              <Conversation
                key={refs
                  .map((r) => r.id + ":" + r.version)
                  .sort()
                  .join(",")}
                pid={pid}
                refs={refs}
                operation="repair"
                refresh={props.refresh}
                annotationRevision={String(annotationRevision)}
                annotationsReady={
                  saved &&
                  refs.every(
                    (r) =>
                      !localStorage.getItem(
                        `comic-annotations:${r.id}:${r.version}`,
                      ),
                  )
                }
              />
            )}
          </aside>
        )}
      </div>
      {candidate && (
        <CandidateReview
          record={heads.find((r) => r.id === candidate.id) || candidate}
          candidates={candidates(candidate)}
          onSaved={(r) => {
            props.onSaved(r);
            void props.refresh();
          }}
          onClose={() => setCandidate(null)}
        />
      )}{" "}
      {history && view && (
        <RecordHistory
          record={view}
          onSaved={props.onSaved}
          onClose={() => setHistory(false)}
        />
      )}{" "}
      {details && view && head && (
        <ImageDetails
          record={view}
          head={head}
          onSaved={(r) => {
            props.onSaved(r);
            void props.refresh();
          }}
          onClose={() => setDetails(false)}
        />
      )}
    </div>
  );
}
function ImageDetails({
  record,
  head,
  onSaved,
  onClose,
}: {
  record: RecordItem;
  head: RecordItem;
  onSaved: (r: RecordItem) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(""),
    [severity, setSeverity] = useState("general"),
    [error, setError] = useState("");
  const save = async (issues: any[]) => {
    try {
      const r = await api<RecordItem>(
        recPath(head),
        json("PUT", {
          expected_version: head.version,
          content: { ...record.content, issues, checked: true },
        }),
      );
      if (record.version === head.adopted)
        await api(
          recPath(head) + "/adopt",
          json("POST", { version: r.version }),
        );
      onSaved(r);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Drawer title="图片资料与问题" onClose={onClose}>
      <Badge source={record.source} />
      <p>
        版本 v{record.version} · {record.content.characters || "人物未标注"} ·{" "}
        {record.content.scene || "场景未标注"}
      </p>
      <ErrorNote message={error} />
      {(record.content.issues || []).map((v: any, i: number) => (
        <div key={i} className="issue">
          <strong>
            {v.severity === "major"
              ? "重大"
              : v.severity === "general"
                ? "一般"
                : "轻微"}
          </strong>
          <p>{v.text}</p>
          <button
            disabled={record.version !== head.version}
            onClick={() =>
              void save(
                record.content.issues.filter((_: any, n: number) => n !== i),
              )
            }
          >
            标为解决
          </button>
        </div>
      ))}
      <label>
        人工观察
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
        <option value="general">一般</option>
        <option value="major">重大</option>
        <option value="minor">轻微</option>
      </select>
      <button
        disabled={!text.trim() || record.version !== head.version}
        onClick={() =>
          void save([
            ...(record.content.issues || []),
            { id: crypto.randomUUID(), text, severity, basis: "人工观察" },
          ])
        }
      >
        保存问题
      </button>
      <button
        disabled={record.version !== head.version}
        onClick={() => void save(record.content.issues || [])}
      >
        记录已检查
      </button>
      {record.version !== head.version && (
        <p>历史检查只读，请切到最新版本记录问题。</p>
      )}
    </Drawer>
  );
}
