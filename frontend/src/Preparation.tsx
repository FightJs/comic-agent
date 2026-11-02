import { useViewState } from "./useViewState";
import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Upload,
  Search,
  Plus,
  ArrowUpRight,
  Sparkles,
  FileText,
  CheckCircle2,
} from "lucide-react";
import { api, base, json, type RecordItem } from "./api";
import { Badge, Empty, ErrorNote, Drawer, reviewLabel } from "./ui";
import { DocumentEditor, RecordHistory } from "./DocumentEditor";
import { useDraft } from "./useDraft";
export type WorkspaceProps = {
  pid: string;
  records: RecordItem[];
  onSaved: (r: RecordItem) => void;
  refresh: () => Promise<void>;
  run: (
    kind: string,
    target?: RecordItem,
    extra?: Record<string, any>,
  ) => Promise<void>;
};

export function Original({ pid, records, refresh }: WorkspaceProps) {
  const originals = records.filter((r) => r.kind === "original"),
    [id, setId] = useViewState(pid + ":original-id", ""),
    [query, setQuery] = useViewState(pid + ":original-query", ""),
    [chapter, setChapter] = useViewState(pid + ":original-chapter", 0),
    [encoding, setEncoding] = useState("auto"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [hit, setHit] = useState(0);
  const current = originals.find((r) => r.id === id) || originals.at(-1);
  const text: string = current?.content.text || "";
  const matches = useMemo(() => {
    if (!query) return [];
    const a: number[] = [];
    let i = text.indexOf(query);
    while (i >= 0 && a.length < 1000) {
      a.push(i);
      i = text.indexOf(query, i + query.length);
    }
    return a;
  }, [text, query]);
  const storedChapters = current?.content.chapters || [];
  const chapters =
    storedChapters.length && storedChapters[0].offset > 0
      ? [{ title: "前言", offset: 0 }, ...storedChapters]
      : storedChapters;
  const start = chapters[chapter]?.offset || 0,
    end = chapters[chapter + 1]?.offset || text.length;
  const visible = text.slice(start, end);
  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("encoding", encoding);
    try {
      const r = await api<RecordItem>(base(pid) + "/text", {
        method: "POST",
        body: form,
      });
      await refresh();
      setId(r.id);
      setChapter(0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const navigateHit = (n: number) => {
    const next = (n + matches.length) % matches.length;
    setHit(next);
    const offset = matches[next];
    let ch = chapters.findIndex(
      (c: any, i: number) =>
        offset >= c.offset && offset < (chapters[i + 1]?.offset || text.length),
    );
    setChapter(Math.max(ch, 0));
    setTimeout(
      () =>
        document
          .querySelector(".reader mark.active-hit")
          ?.scrollIntoView({ block: "center" }),
      50,
    );
  };
  const highlighted = () => {
    if (!query) return visible;
    const parts = visible.split(query);
    let offset = start;
    return parts.flatMap((p, i) => {
      if (!i) {
        offset += p.length;
        return [p];
      }
      const active = offset === matches[hit];
      offset += query.length + p.length;
      return [
        <mark className={active ? "active-hit" : ""} key={"m" + i}>
          {query}
        </mark>,
        p,
      ];
    });
  };
  return (
    <>
      <div className="section-tools">
        <div className="actions">
          <select
            aria-label="导入编码"
            value={encoding}
            onChange={(e) => setEncoding(e.target.value)}
          >
            <option value="auto">自动识别编码</option>
            <option value="utf-8-sig">UTF-8</option>
            <option value="gb18030">GB18030</option>
          </select>
          <label className={`button primary ${busy ? "disabled" : ""}`}>
            <Upload size={16} />
            {busy ? "正在导入…" : "导入 TXT"}
            <input
              aria-label="导入小说"
              type="file"
              accept=".txt"
              disabled={busy}
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.target.value = "";
              }}
              className="file-input"
            />
          </label>
        </div>
        <span className="muted">仅本机保存 · 原件只读 · 最大 20MB</span>
      </div>
      <ErrorNote message={error} />
      {!current ? (
        <Empty
          title="从一本小说开始"
          action={
            <span className="muted">
              导入后可搜索全文、按章节定位，并保留原始文件。
            </span>
          }
        >
          选择 TXT 原著，为后续改编建立可追溯的依据。
        </Empty>
      ) : (
        <div className="reader-shell">
          <aside className="chapter-list">
            <label>
              原著版本
              <select
                value={current.id}
                onChange={(e) => {
                  setId(e.target.value);
                  setChapter(0);
                }}
              >
                {originals.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title}
                  </option>
                ))}
              </select>
            </label>
            <div className="file-info">
              <FileText size={15} />
              {text.length.toLocaleString()} 字 · {current.content.encoding}
            </div>
            {(chapters.length ? chapters : [{ title: "全文" }]).map(
              (c: any, i: number) => (
                <button
                  key={i}
                  className={i === chapter ? "selected" : ""}
                  onClick={() => setChapter(i)}
                >
                  {c.title}
                </button>
              ),
            )}
          </aside>
          <div className="reader-main">
            <div className="search">
              <Search size={17} />
              <input
                aria-label="搜索原著"
                placeholder="搜索原著中的人物、事件或句子"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setHit(0);
                }}
              />
              <span>{query ? `${matches.length} 处` : ""}</span>
              {matches.length > 0 && (
                <button onClick={() => navigateHit(hit + 1)}>下一处</button>
              )}
            </div>
            <div className="reader">
              <div className="reader-meta">
                <Badge source="import" />
                <span>只读原著</span>
              </div>
              <h2>{chapters[chapter]?.title || current.title}</h2>
              <div className="novel-text">{highlighted()}</div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function Memory({ records, run }: WorkspaceProps) {
  const r = records.filter((x) => x.kind === "memory").at(-1),
    [filter, setFilter] = useState("全部"),
    [selected, setSelected] = useState<any>(null);
  const nodes: Node[] = (r?.content.nodes || [])
    .filter((n: any) => filter === "全部" || n.type === filter)
    .map((n: any, i: number) => ({
      id: n.id,
      position: { x: (i % 2) * 280 + 80, y: Math.floor(i / 2) * 190 + 80 },
      data: {
        label: (
          <div>
            <small>{n.type}</small>
            <strong>{n.label}</strong>
          </div>
        ),
      },
      className: "entity-node",
    }));
  const edges: Edge[] = (r?.content.edges || [])
    .filter(
      (e: any) =>
        nodes.some((n) => n.id === e.source) &&
        nodes.some((n) => n.id === e.target),
    )
    .map((e: any, i: number) => ({
      ...e,
      id: String(i),
      style: { stroke: "#8a956e" },
      labelStyle: { fill: "#3c4430", fontSize: 12 },
    }));
  return (
    <>
      <div className="section-tools">
        <div className="actions">
          <select
            aria-label="实体类型"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            {["全部", "人物", "场景", "道具"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <span className="muted">点击实体查看属性与来源</span>
        </div>
        <button className="primary" onClick={() => void run("memory", r)}>
          <Sparkles size={16} />
          模拟理解与提取
        </button>
      </div>
      <div className="notice">
        AI 理解与 GraphRAG 尚未接入。示例关系不代表对当前小说的提取结果。
      </div>
      <details
        className="gate-details"
        style={{ marginTop: 0, marginBottom: 18 }}
      >
        <summary>
          章节覆盖与事件记录<span>正式理解尚未执行</span>
        </summary>
        <div>
          {records
            .filter((x) => x.kind === "original")
            .map((original) => (
              <div key={original.id}>
                <strong>{original.title}</strong>
                <p>
                  {(original.content.chapters?.length
                    ? original.content.chapters
                    : [{ title: "全文" }]
                  )
                    .map((chapter: any) => chapter.title + " · 待理解")
                    .join("；")}
                </p>
              </div>
            ))}
          {!records.some((x) => x.kind === "original") && (
            <p>请先导入原著以建立章节覆盖范围。</p>
          )}
          {r && (
            <>
              <h4>模拟事件 · 非原著提取</h4>
              <p>
                阿青到访旧院 → 发现来信 →
                寻找写信人。依据：预置流程样例，无当前小说原文定位。
              </p>
            </>
          )}
        </div>
      </details>
      {!r ? (
        <Empty title="原著中的关系，尚待整理">
          模拟提取可体验人物、场景与关系的交互；正式事实仍需后续模型接入。
        </Empty>
      ) : (
        <div className="graph">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            onNodeClick={(_, n) =>
              setSelected(r.content.nodes.find((x: any) => x.id === n.id))
            }
          >
            <Background color="#dce0d4" gap={24} />
            <Controls />
          </ReactFlow>
        </div>
      )}
      {selected && (
        <Drawer title={selected.label} onClose={() => setSelected(null)}>
          <Badge source={r?.source || "mock"} />
          <h3>{selected.type}属性</h3>
          <p>{selected.description}</p>
          <h3>来源依据</h3>
          <p>{selected.source}</p>
          <h3>关联关系</h3>
          {r?.content.edges
            .filter(
              (e: any) => e.source === selected.id || e.target === selected.id,
            )
            .map((e: any, i: number) => (
              <p key={i}>{e.label}</p>
            ))}
        </Drawer>
      )}
    </>
  );
}

export function Documents({
  kind,
  ...props
}: WorkspaceProps & { kind: "skeleton" | "outline" }) {
  const rows = props.records.filter((r) => r.kind === kind),
    [id, setId] = useViewState(props.pid + ":" + kind + ":document-id", ""),
    [error, setError] = useState("");
  const record = rows.find((r) => r.id === id) || rows.at(-1);
  useEffect(() => {
    if (record && record.id !== id) setId(record.id);
  }, [record?.id, id, setId]);
  const create = async () => {
    try {
      const r = await api<RecordItem>(
        base(props.pid) + "/records",
        json("POST", {
          kind,
          title: kind === "skeleton" ? "全书改编骨架" : "分集细纲",
          content: { html: "<h2>创作草稿</h2><p></p>" },
        }),
      );
      props.onSaved(r);
      setId(r.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <div className="section-tools">
        <div className="actions">
          {rows.length > 0 && (
            <select
              aria-label="选择文档"
              value={record?.id}
              onChange={(e) => setId(e.target.value)}
            >
              {rows.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title} · v{r.version}
                  {r.content.pending_for ? " · 待处理回复" : ""}
                </option>
              ))}
            </select>
          )}
          {record && (
            <>
              <Badge source={record.source} />
              <span className="status-text">{reviewLabel(record.review)}</span>
            </>
          )}
        </div>
        <div className="actions">
          <button onClick={() => void create()}>
            <Plus size={16} />
            新建草稿
          </button>
          <button
            className="primary"
            onClick={() => void props.run(kind, record)}
          >
            <Sparkles size={16} />
            模拟生成
          </button>
        </div>
      </div>
      <ErrorNote message={error} />
      {record ? (
        <DocumentEditor
          key={record.id}
          record={record}
          onSaved={props.onSaved}
        />
      ) : (
        <Empty
          title={
            kind === "skeleton"
              ? "建立全书的叙事骨架"
              : "把全书故事落实到每一话"
          }
          action={
            <button onClick={() => void create()}>
              <Plus size={16} />
              开始写草稿
            </button>
          }
        >
          可以直接自由编辑，或生成明确标识的模拟样例体验流程。
        </Empty>
      )}
    </>
  );
}

function AssetDetails({
  record,
  onSaved,
  onClose,
}: {
  record: RecordItem;
  onSaved: (r: RecordItem) => void;
  onClose: () => void;
}) {
  const draft = useDraft(record, onSaved),
    [review, setReview] = useState(false),
    [message, setMessage] = useState(""),
    [assetError, setAssetError] = useState("");
  const uploadVersion = async (file?: File) => {
    if (!file) return;
    const head = draft.head.current;
    const form = new FormData();
    form.append("file", file);
    form.append("kind", record.kind);
    form.append("record_id", record.id);
    form.append("expected_version", String(head.version));
    try {
      const next = await api<RecordItem>(base(record.project_id) + "/images", {
        method: "POST",
        body: form,
      });
      onSaved(next);
      draft.accept(next);
      draft.setContent(next.content);
      setMessage("已导入新版本，需重新审核。");
    } catch (e) {
      setAssetError((e as Error).message);
    }
  };
  const choose = async () => {
    try {
      await api(
        base(record.project_id) + "/style-selection",
        json("POST", {
          record_id: record.id,
          version: draft.head.current.version,
        }),
      );
      setMessage("已采用此画风版本。修改后需重新审核并选用。");
      onSaved(draft.head.current);
    } catch (e) {
      setAssetError((e as Error).message);
    }
  };
  return (
    <Drawer title={record.title} onClose={onClose}>
      <Badge source={record.source} />
      <ErrorNote message={assetError} />
      {message && <p className="notice">{message}</p>}
      <div className="actions">
        <label className="button">
          导入新版本
          <input
            className="file-input"
            type="file"
            aria-label="导入资产新版本"
            accept="image/png,image/jpeg"
            onChange={(e) => {
              void uploadVersion(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        {record.kind === "style" && (
          <button onClick={() => void choose()}>采用此画风</button>
        )}
      </div>
      {record.content.url && (
        <img
          className="asset-detail-image"
          src={record.content.url}
          alt={record.title}
        />
      )}
      <div className="form-grid">
        {[
          ["category", "分类"],
          ["state", "衣装／场景状态"],
          ["characters", "关联人物"],
          ["scene", "关联场景"],
          ["description", "资产描述"],
          ["source_note", "来源说明"],
        ].map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              value={draft.content[key] || ""}
              onChange={(e) =>
                draft.setContent({ ...draft.content, [key]: e.target.value })
              }
            />
          </label>
        ))}
      </div>
      <ErrorNote message={draft.error} />
      <div className="actions">
        <button className="primary" onClick={() => draft.retry()}>
          保存属性
        </button>
        <button onClick={() => setReview(true)}>版本与审核</button>
        <span className="muted">{draft.status}</span>
      </div>
      {review && (
        <RecordHistory
          record={draft.head.current}
          onSaved={onSaved}
          onClose={() => setReview(false)}
        />
      )}
    </Drawer>
  );
}

export function Assets({
  kind,
  ...props
}: WorkspaceProps & { kind: "style" | "asset" }) {
  const [filter, setFilter] = useState("全部"),
    [source, setSource] = useState("all"),
    [status, setStatus] = useState("all"),
    [selected, setSelected] = useState<RecordItem | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const rows = props.records.filter(
    (r) =>
      r.kind === kind &&
      (filter === "全部" || r.content.category === filter) &&
      (source === "all" || r.source === source) &&
      (status === "all" || r.review === status),
  );
  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("category", filter === "全部" ? "人物" : filter);
    try {
      await api(base(props.pid) + "/images", { method: "POST", body: form });
      await props.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="section-tools">
        <div className="actions">
          <select
            aria-label="资产分类"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            {["全部", "人物", "场景", "道具"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <select
            aria-label="资产来源"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="all">全部来源</option>
            <option value="import">人工导入</option>
            <option value="mock">模拟</option>
          </select>
          <select
            aria-label="审核状态"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">全部审核状态</option>
            <option value="pending">待审核</option>
            <option value="approved">已通过</option>
            <option value="changes">需修改</option>
          </select>
        </div>
        <div className="actions">
          <label className="button">
            <Upload size={16} />
            {busy ? "导入中…" : "导入图片"}
            <input
              aria-label="导入资产图片"
              className="file-input"
              disabled={busy}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <button
            className="primary"
            onClick={async () => {
              if (kind === "style") {
                for (let i = 0; i < 3; i++)
                  await props.run("style", undefined, { panel: i + 1 });
              } else await props.run("asset");
            }}
          >
            <Sparkles size={16} />
            {kind === "style" ? "模拟三套画风" : "模拟资产生成"}
          </button>
        </div>
      </div>
      <ErrorNote message={error} />
      <div className="notice">
        {kind === "style"
          ? "先比较画风与代表样例，再补齐全书资产。三套模拟图仅为界面占位，不代表真实画风生成。"
          : "人物、场景、道具按剧情状态整理。全书资产审核完成后，才满足正式制作的前期条件。"}
      </div>
      {rows.length ? (
        <div className="asset-grid">
          {rows.map((r) => (
            <button
              className="asset-tile"
              key={r.id}
              onClick={() => setSelected(r)}
            >
              <div className="asset-image">
                {r.content.url ? (
                  <img src={r.content.url} alt={r.title} loading="lazy" />
                ) : (
                  <FileText />
                )}
                <span className="tile-source">
                  <Badge source={r.source} />
                </span>
              </div>
              <div className="asset-caption">
                <strong>{r.title}</strong>
                <span>
                  {r.content.category} · {r.content.state || "默认状态"}
                </span>
                <div>
                  <span className="status-text">{reviewLabel(r.review)}</span>
                  <small>v{r.version}</small>
                  <ArrowUpRight size={15} />
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <Empty
          title={
            kind === "style"
              ? "为这部作品确定视觉语言"
              : "让每个角色与场景都有依据"
          }
        >
          导入 PNG/JPEG 参考图，记录状态与来源，并审核准确版本。
        </Empty>
      )}
      {selected && (
        <AssetDetails
          key={selected.id}
          record={selected}
          onSaved={(r) => {
            props.onSaved(r);
            setSelected(r);
          }}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

export function GateSummary({ pid }: { pid: string }) {
  const [value, setValue] = useState<any>(null);
  useEffect(() => {
    api(base(pid) + "/gates")
      .then(setValue)
      .catch(() => {});
  }, [pid]);
  return (
    <div className="gate-summary">
      <CheckCircle2 size={18} />
      <div>
        <strong>正式制作准备检查</strong>
        <p>
          {value?.reasons?.join("、") || "正在检查前期条件"}
          {value?.reasons?.length ? "尚未完成。" : ""}
        </p>
        <small>可浏览与模拟；真实 AI 生成尚未接入。</small>
      </div>
    </div>
  );
}
