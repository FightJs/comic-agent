import { useViewState } from "./useViewState";
import { useEffect, useState } from "react";
import { Plus, Sparkles, History, Search, ImagePlus } from "lucide-react";
import { api, base, json, type RecordItem } from "./api";
import { Badge, Empty, ErrorNote, reviewLabel, Drawer } from "./ui";
import { RecordHistory } from "./DocumentEditor";
import { useDraft } from "./useDraft";
import type { WorkspaceProps } from "./Preparation";
export type ProductionProps = WorkspaceProps & {
  batch: number;
  episode: number;
  panel: number;
  onPanel: (p: number) => void;
  onLocation: (episode: number, panel: number) => void;
};
const fields = [
  ["characters", "角色"],
  ["scene", "场景"],
  ["weather", "天气"],
  ["time", "时间"],
  ["shot", "景别"],
  ["camera", "机位"],
  ["description", "画面内容"],
  ["dialogue", "台词"],
  ["sfx", "特效字"],
  ["note", "备注"],
];
function PanelForm({
  record,
  onSaved,
  assets,
}: {
  record: RecordItem;
  onSaved: (r: RecordItem) => void;
  assets: RecordItem[];
}) {
  const draft = useDraft(record, onSaved),
    [history, setHistory] = useState(false),
    [assetId, setAssetId] = useState("");
  const isPackage = record.kind === "package";
  const [boundReferences, setBoundReferences] = useState<RecordItem[]>([]),
    [boundScript, setBoundScript] = useState<RecordItem | null>(null),
    [referenceError, setReferenceError] = useState("");
  const referenceKey = JSON.stringify(draft.content.references || []);
  useEffect(() => {
    let alive = true;
    Promise.all(
      (draft.content.references || []).map((ref: any) =>
        api<RecordItem>(
          base(record.project_id) + `/records/${ref.id}?version=${ref.version}`,
        ),
      ),
    )
      .then((rows) => {
        if (alive) setBoundReferences(rows);
      })
      .catch((e) => setReferenceError(e.message));
    return () => {
      alive = false;
    };
  }, [referenceKey]);
  useEffect(() => {
    if (!draft.content.script_id) return;
    api<RecordItem>(
      base(record.project_id) +
        `/records/${draft.content.script_id}?version=${draft.content.script_version}`,
    )
      .then(setBoundScript)
      .catch((e) => setReferenceError(e.message));
  }, [draft.content.script_id, draft.content.script_version]);

  const addRef = () => {
    const a = assets.find((x) => x.id === assetId);
    if (!a) return;
    draft.setContent({
      ...draft.content,
      references: [
        ...(draft.content.references || []),
        { id: a.id, version: a.version, purpose: "身份参考" },
      ],
    });
    setAssetId("");
  };
  return (
    <div className="panel-form">
      <div className="detail-heading">
        <div>
          <span className="muted">
            第 {record.content.episode} 话 / 第 {record.content.panel} 格
          </span>
          <h3>{isPackage ? "逐格生图包" : "画面与叙事"}</h3>
        </div>
        <Badge source={record.source} />
      </div>
      <ErrorNote message={draft.error} />
      {draft.error && (
        <button onClick={() => void draft.resolve()}>
          保留编辑并读取最新版本号
        </button>
      )}
      <ErrorNote message={referenceError} />
      {isPackage && (
        <details className="bound-script">
          <summary>
            绑定脚本 · {boundScript ? `v${boundScript.version}` : "尚未绑定"}
          </summary>
          {boundScript ? (
            <>
              <Badge source={boundScript.source} />
              <p>{boundScript.content.description || "未填写画面内容"}</p>
              <p>台词：{boundScript.content.dialogue || "无"}</p>
              <small>
                角色：{boundScript.content.characters || "未填写"} · 场景：
                {boundScript.content.scene || "未填写"}
              </small>
            </>
          ) : (
            <p>请先在本话格建立逐格脚本，再创建生图包。</p>
          )}
        </details>
      )}
      <div className="form-grid">
        {(isPackage
          ? [
              ["camera", "镜头与画面要求"],
              ["prompt", "完整直接提示词"],
              ["parameters", "执行参数"],
              ["dependencies", "前图依赖"],
              ["missing", "缺件与检查目标"],
            ]
          : fields
        ).map(([key, label]) => (
          <label
            key={key}
            className={
              [
                "description",
                "dialogue",
                "note",
                "prompt",
                "missing",
                "dependencies",
              ].includes(key)
                ? "full"
                : ""
            }
          >
            {label}
            {[
              "description",
              "dialogue",
              "note",
              "prompt",
              "missing",
              "dependencies",
            ].includes(key) ? (
              <textarea
                rows={key === "prompt" ? 7 : 3}
                value={draft.content[key] || ""}
                onChange={(e) =>
                  draft.setContent({ ...draft.content, [key]: e.target.value })
                }
              />
            ) : (
              <input
                value={draft.content[key] || ""}
                onChange={(e) =>
                  draft.setContent({ ...draft.content, [key]: e.target.value })
                }
              />
            )}
          </label>
        ))}
      </div>
      {isPackage && (
        <>
          <h4>实际参考与用途</h4>
          <div className="reference-list">
            {(draft.content.references || []).map((ref: any, i: number) => {
              const a = boundReferences.find(
                (x) => x.id === ref.id && x.version === ref.version,
              );
              return (
                <div key={i}>
                  {a?.content.url && (
                    <img
                      src={a.content.url}
                      alt={`${a.title} 版本 ${ref.version}`}
                    />
                  )}
                  <div>
                    <strong>{a?.title || "历史参考"}</strong>
                    <small>v{ref.version}</small>
                    <input
                      aria-label="参考用途"
                      value={ref.purpose}
                      onChange={(e) =>
                        draft.setContent({
                          ...draft.content,
                          references: draft.content.references.map(
                            (r: any, n: number) =>
                              n === i ? { ...r, purpose: e.target.value } : r,
                          ),
                        })
                      }
                    />
                  </div>
                  <button
                    onClick={() =>
                      draft.setContent({
                        ...draft.content,
                        references: draft.content.references.filter(
                          (_: any, n: number) => n !== i,
                        ),
                      })
                    }
                  >
                    移除
                  </button>
                </div>
              );
            })}
          </div>
          <div className="actions">
            <select
              aria-label="选择参考资产"
              value={assetId}
              onChange={(e) => setAssetId(e.target.value)}
            >
              <option value="">选择本项目资产</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title} · v{a.version}
                </option>
              ))}
            </select>
            <button onClick={addRef} disabled={!assetId}>
              <ImagePlus size={16} />
              添加参考
            </button>
          </div>
          <p className="muted">
            引用绑定资产版本；引用模拟资产后，本包也保留模拟来源。
          </p>
        </>
      )}
      <div className="sticky-actions">
        <span className="save-state">{draft.status}</span>
        <button onClick={() => setHistory(true)}>
          <History size={16} />
          版本与审核
        </button>
        <button className="primary" onClick={() => draft.retry()}>
          保存本格
        </button>
      </div>
      {history && (
        <RecordHistory
          record={draft.head.current}
          onSaved={onSaved}
          onClose={() => setHistory(false)}
        />
      )}
    </div>
  );
}
export function Scripts(
  props: ProductionProps & { kind: "script" | "package" },
) {
  const [query, setQuery] = useViewState(
      props.pid +
        ":" +
        props.batch +
        ":" +
        props.episode +
        ":" +
        props.kind +
        ":query",
      "",
    ),
    [error, setError] = useState(""),
    [sort, setSort] = useViewState(
      props.pid + ":" + props.batch + ":" + props.kind + ":sort",
      false,
    );
  const [batchReview, setBatchReview] = useState(false),
    [reviewNote, setReviewNote] = useState(""),
    [batchHistory, setBatchHistory] = useState<any[]>([]);
  useEffect(() => {
    if (batchReview)
      api<any[]>(base(props.pid) + "/batch-reviews?batch=" + props.batch)
        .then(setBatchHistory)
        .catch((e) => setError(e.message));
  }, [batchReview]);
  const batchScripts = props.records.filter(
    (r) =>
      r.kind === "script" &&
      r.content.batch === props.batch &&
      !r.content.pending_for,
  );
  const reviewBatch = async (decision: string) => {
    try {
      await api(
        base(props.pid) + "/batch-review",
        json("POST", {
          batch: props.batch,
          records: batchScripts.map((r) => ({ id: r.id, version: r.version })),
          decision,
          note: reviewNote,
        }),
      );
      await props.refresh();
      setBatchReview(false);
      setReviewNote("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const [selectedId, setSelectedId] = useViewState(
    props.pid +
      ":" +
      props.batch +
      ":" +
      props.episode +
      ":" +
      props.kind +
      ":selected",
    "",
  );
  const all = props.records.filter(
    (r) =>
      r.kind === props.kind &&
      r.content.batch === props.batch &&
      r.content.episode === props.episode,
  );
  const rows = all
    .filter((r) => !query || Object.values(r.content).join(" ").includes(query))
    .sort((a, b) =>
      sort
        ? b.content.panel - a.content.panel
        : a.content.panel - b.content.panel,
    );
  const record =
    all.find((r) => r.id === selectedId && r.content.panel === props.panel) ||
    all.find(
      (r) => r.content.panel === props.panel && !r.content.pending_for,
    ) ||
    all.find((r) => r.content.panel === props.panel);
  const create = async () => {
    try {
      const panel =
        props.kind === "package"
          ? props.panel
          : Math.max(0, ...all.map((r) => r.content.panel)) + 1;
      const script = props.records.find(
        (r) =>
          r.kind === "script" &&
          r.content.episode === props.episode &&
          r.content.panel === panel &&
          r.content.batch === props.batch,
      );
      const r = await api<RecordItem>(
        base(props.pid) + "/records",
        json("POST", {
          kind: props.kind,
          title: `第${props.episode}话 第${panel}格`,
          source: script?.source === "mock" ? "mock" : "manual",
          content: {
            batch: props.batch,
            episode: props.episode,
            panel,
            ...(props.kind === "package"
              ? {
                  script_id: script?.id,
                  script_version: script?.version,
                  references: [],
                  prompt: "",
                  missing: "待补充脚本和参考依据",
                }
              : { description: "", characters: "", scene: "" }),
          },
        }),
      );
      props.onSaved(r);
      setSelectedId(r.id);
      props.onPanel(panel);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <div className="section-tools">
        <div className="search small">
          <Search size={15} />
          <input
            aria-label="筛选话格"
            value={query}
            placeholder="筛选角色、场景、内容"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="actions">
          {props.kind === "script" && (
            <button
              disabled={!batchScripts.length}
              onClick={() => setBatchReview(true)}
            >
              审核本批脚本
            </button>
          )}
          <button
            onClick={() => void create()}
            disabled={props.kind === "package" && !!record}
          >
            <Plus size={16} />
            {props.kind === "package" ? "建立本格生图包" : "新增一格"}
          </button>
          <button
            className="primary"
            onClick={() =>
              void props.run(props.kind, record, {
                batch: props.batch,
                episode: props.episode,
                panel: props.panel,
              })
            }
          >
            <Sparkles size={16} />
            模拟{props.kind === "package" ? "编排" : "脚本"}
          </button>
        </div>
      </div>
      <ErrorNote message={error} />
      {all.length ? (
        <div className="script-split">
          <div className="script-table">
            <table>
              <thead>
                <tr>
                  <th>
                    <button
                      className="text-button"
                      onClick={() => setSort(!sort)}
                    >
                      格号 {sort ? "↓" : "↑"}
                    </button>
                  </th>
                  <th>内容</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className={record?.id === r.id ? "active" : ""}
                    onClick={() => {
                      setSelectedId(r.id);
                      props.onPanel(r.content.panel);
                    }}
                  >
                    <td>
                      <button
                        className="text-button"
                        onClick={() => {
                          setSelectedId(r.id);
                          props.onPanel(r.content.panel);
                        }}
                      >
                        {String(r.content.panel).padStart(3, "0")}
                      </button>
                    </td>
                    <td>
                      <strong>
                        {r.content.characters ||
                          r.content.camera ||
                          "未填写角色"}
                      </strong>
                      {r.content.pending_for && (
                        <span className="badge mock">待处理回复</span>
                      )}
                      <p>
                        {r.content.description ||
                          r.content.prompt ||
                          "等待编辑画面内容"}
                      </p>
                      <small>
                        {r.content.scene || "未指定场景"}{" "}
                        <Badge source={r.source} />
                      </small>
                    </td>
                    <td>
                      <span className="status-text">
                        {reviewLabel(r.review)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && (
              <p className="muted padded">没有匹配的格，请调整筛选。</p>
            )}
          </div>
          {record ? (
            <PanelForm
              key={record.id}
              record={record}
              onSaved={props.onSaved}
              assets={props.records.filter((r) =>
                ["asset", "style"].includes(r.kind),
              )}
            />
          ) : (
            <Empty title="选择一个话格">从左侧表格选择需要编辑的画面。</Empty>
          )}
        </div>
      ) : (
        <Empty
          title={
            props.kind === "package"
              ? "把本格设计整理为完整输入"
              : "这一话的第一个画面"
          }
          action={
            <button onClick={() => void create()}>
              <Plus size={16} />
              创建{props.kind === "package" ? "生图包" : "第一格"}
            </button>
          }
        >
          每一格都有稳定的身份、独立版本和对应审核依据。
        </Empty>
      )}
      {batchReview && (
        <Drawer title="批次脚本审核" onClose={() => setBatchReview(false)}>
          <p>
            第 {(props.batch - 1) * 10 + 1}–{props.batch * 10}{" "}
            话范围内，审核当前已有 {batchScripts.length}{" "}
            格的准确版本。未建立的格不视为已完成。
          </p>
          <p className="notice">模拟脚本仅记录模拟审核，不满足正式制作条件。</p>
          <label>
            批次审核意见
            <textarea
              value={reviewNote}
              onChange={(e) => setReviewNote(e.target.value)}
            />
          </label>
          <div className="actions">
            <button
              className="primary"
              onClick={() => void reviewBatch("approved")}
            >
              通过所列版本
            </button>
            <button onClick={() => void reviewBatch("changes")}>
              需要修改
            </button>
          </div>
          <h3>批次历史</h3>
          {batchHistory.map((h) => (
            <div className="task" key={h.id}>
              <strong>
                {h.stale ? "输入已变化，需重审" : reviewLabel(h.decision)}
              </strong>
              <p>{h.note || "未填写意见"}</p>
              <small>
                {h.records.length} 格 ·{" "}
                {new Date(h.created).toLocaleString("zh-CN")}
              </small>
              <details>
                <summary>版本清单</summary>
                {h.records.map((ref: any) => (
                  <p key={ref.id}>
                    {ref.id.slice(0, 8)} · v{ref.version} ·{" "}
                    {ref.source === "mock" ? "模拟" : "正式来源"}
                  </p>
                ))}
              </details>
            </div>
          ))}
        </Drawer>
      )}
    </>
  );
}
