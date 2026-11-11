import {ImageDependencies} from "./ImageDependencies";
import {ImageBatches} from "./ImageBatches";
import {ImageGeneration} from "./ImageGeneration";
import { PackageTable } from "./PackageTable";
import { Select } from "./Select";
import { useEffect, useState, useRef } from "react";
import { api, base, json, recPath, RecordItem } from "./api";
import { Badge, Drawer, Empty, ErrorNote, reviewLabel } from "./ui";
import { RecordHistory } from "./DocumentEditor";
import { useDraft } from "./useDraft";
import { useViewState } from "./useViewState";
import type { WorkspaceProps } from "./Preparation";
import {
  CandidateReview,
  Conversation,
  RangeGeneration,
  GroupResults,
  submitJob,
} from "./Workflow";
import {
  composePrompt,
  primaryRecord,
  promptFields,
  scriptFields,
} from "./workflowLogic";
import "./production.css";
export type ProductionProps = WorkspaceProps & {
  batch: number;
  episode: number;
  panel: number;
  onPanel: (p: number) => void;
  onLocation: (episode: number, panel: number) => void;
};
function ScriptDetail({
  record,
  onSaved,
  onClose,
}: {
  record: RecordItem;
  onSaved: (r: RecordItem) => void;
  onClose: () => void;
}) {
  const d = useDraft(record, onSaved);
  const [edit, setEdit] = useState(false),
    [history, setHistory] = useState(false);
  return (
    <Drawer
      title={`第${record.content.episode}话 · 第${record.content.panel}格`}
      onClose={onClose}
    >
      <div className="actions">
        <Badge source={record.source} />
        <span>
          v{record.version} · {reviewLabel(record.review)}
        </span>
        <button onClick={() => setEdit(!edit)}>
          {edit ? "返回阅读" : "手动修订"}
        </button>
        <button onClick={() => setHistory(true)}>版本与审核</button>
      </div>
      <ErrorNote message={d.error} />
      {d.error && (
        <button onClick={() => void d.resolve()}>
          保留编辑并读取最新版本号
        </button>
      )}
      {scriptFields.slice(1).map(([k, label]) => (
        <section className="script-reading-field" key={k}>
          <strong>{label}</strong>
          {edit ? (
            <textarea
              value={d.content[k] || ""}
              onChange={(e) =>
                d.setContent({ ...d.content, [k]: e.target.value })
              }
            />
          ) : (
            <p>{d.content[k] || "—"}</p>
          )}
        </section>
      ))}
      {edit && <button onClick={() => void d.save()}>保存修订</button>}
      {history && (
        <RecordHistory
          record={record}
          onSaved={onSaved}
          onClose={() => setHistory(false)}
        />
      )}
    </Drawer>
  );
}
function PackageDetail({
  record,
  ...props
}: ProductionProps & { record: RecordItem }) {
  const d = useDraft(record, props.onSaved);
  const [refs, setRefs] = useState<RecordItem[]>([]),
    [error, setError] = useState(""),
    [tab, setTab] = useState("package"),
    [asset, setAsset] = useState("");
  const bound = props.records.find((r) => r.id === d.content.script_id);
  const stale = bound && bound.version !== d.content.script_version;
  useEffect(() => {
    let alive = true;
    Promise.all(
      (d.content.references || []).map((r: any) =>
        api<RecordItem>(
          base(props.pid) + `/records/${r.id}?version=${r.version}`,
        ),
      ),
    )
      .then((rows) => {
        if (alive) setRefs(rows);
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [JSON.stringify(d.content.references)]);
  const setPart = (key: string, value: string) =>
    d.setContent((c) => {
      const next = { ...c, [key]: value };
      if (c.prompt_mode !== "override" && !(c.prompt && !c.prompt_mode))
        next.prompt = composePrompt(next);
      else next.prompt_mode = "override";
      return next;
    });
  return (
    <article className="package-reader">
      <header className="detail-heading">
        <div>
          <small>
            第{record.content.episode}话 / 第{record.content.panel}格
          </small>
          <h2>逐格生图包</h2>
        </div>
        <Badge source={record.source} />
      </header>
      <div className="segmented">
        <button
          className={tab === "package" ? "active" : ""}
          onClick={() => setTab("package")}
        >
          内容与资产
        </button>
        <button
          className={tab === "chat" ? "active" : ""}
          onClick={() => setTab("chat")}
        >
          与 AI 讨论修改
        </button>
      </div>
      <ErrorNote message={d.error || error} />
      {d.error && (
        <button onClick={() => void d.resolve()}>
          保留编辑并读取最新版本号
        </button>
      )}
      {stale && (
        <div className="notice">
          绑定脚本 v{d.content.script_version}，当前已为 v{bound.version}
          。本包依据已过期，旧内容仍保留。
        </div>
      )}
      {tab === "chat" ? (
        <Conversation
          key={record.id}
          pid={props.pid}
          refs={[record]}
          operation="rewrite"
          refresh={props.refresh}
        />
      ) : (
        <>
          <details>
            <summary>
              脚本依据 · v{d.content.script_version || "未绑定"}
            </summary>
            <BoundScript
              pid={props.pid}
              id={d.content.script_id}
              version={d.content.script_version}
            />
          </details>
          {["人物", "场景", "其他"].map((category) => (
            <section key={category}>
              <h3>{category === "其他" ? "其他参考" : category + "资产"}</h3>
              <div className="asset-strip">
                {refs
                  .filter((r) =>
                    category === "其他"
                      ? !["人物", "场景"].includes(r.content.category)
                      : r.content.category === category,
                  )
                  .map((r) => (
                    <figure key={r.id}>
                      <img src={r.content.url} alt={r.title} />
                      <figcaption>
                        <strong>{r.title}</strong>
                        <span>
                          v{r.version} · {r.content.state || "默认状态"}
                        </span>
                        <input
                          aria-label={r.title + "参考用途"}
                          value={
                            (d.content.references || []).find(
                              (x: any) => x.id === r.id,
                            )?.purpose || ""
                          }
                          onChange={(e) =>
                            d.setContent({
                              ...d.content,
                              references: d.content.references.map((x: any) =>
                                x.id === r.id
                                  ? { ...x, purpose: e.target.value }
                                  : x,
                              ),
                            })
                          }
                        />
                        <button
                          onClick={() =>
                            d.setContent({
                              ...d.content,
                              references: d.content.references.filter(
                                (x: any) => x.id !== r.id,
                              ),
                            })
                          }
                        >
                          移除参考
                        </button>
                      </figcaption>
                    </figure>
                  ))}
                {!refs.some((r) =>
                  category === "其他"
                    ? !["人物", "场景"].includes(r.content.category)
                    : r.content.category === category,
                ) && <p className="muted">尚未绑定{category}参考</p>}
              </div>
            </section>
          ))}
          <div className="actions">
            <Select
              aria-label="添加资产"
              value={asset}
              onChange={(e) => setAsset(e.target.value)}
            >
              <option value="">选择资产或画风</option>
              {props.records
                .filter(
                  (r) =>
                    ["asset", "style"].includes(r.kind) && primaryRecord(r),
                )
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title} · v{r.adopted}
                  </option>
                ))}
            </Select>
            <button
              disabled={!asset}
              onClick={() => {
                const r = props.records.find((r) => r.id === asset)!;
                if (
                  !(d.content.references || []).some((x: any) => x.id === asset)
                )
                  d.setContent({
                    ...d.content,
                    references: [
                      ...(d.content.references || []),
                      {
                        id: r.id,
                        version: r.adopted,
                        purpose: r.content.category || "画风",
                      },
                    ],
                  });
                setAsset("");
              }}
            >
              绑定采用版本
            </button>
          </div>
          <ImageDependencies id={record.id} records={props.records} content={d.content} onChange={d.setContent}/>
          <h3>直接提示词拆分</h3>
          {promptFields.map(([k, label]) => (
            <label className="prompt-section" key={k}>
              {label}
              <textarea
                rows={k === "content_prompt" ? 5 : 3}
                value={d.content[k] || ""}
                onChange={(e) => setPart(k, e.target.value)}
                placeholder={
                  record.content.prompt && !record.content.prompt_mode
                    ? "旧包未拆分，请人工填写或重新生成生图包"
                    : "尚未填写"
                }
              />
            </label>
          ))}
          <div className="detail-heading">
            <h3>{d.content.generation_dependencies?.length||d.content.previous_image_dependencies?.length?"生图包完整提示词":"最终发送的完整提示词"}</h3>
            <span>
              {d.content.prompt_mode === "override"
                ? "手动覆盖"
                : !d.content.prompt_mode && d.content.prompt
                  ? "旧包完整文本 · 未拆分"
                  : "由分段组合"}
            </span>
          </div>
          {d.content.prompt_mode === "override" && (
            <div className="notice">
              当前使用手工完整文本；修改分段不会覆盖它。
              <button
                onClick={() =>
                  d.setContent({
                    ...d.content,
                    prompt: composePrompt(d.content),
                    prompt_mode: "composed",
                  })
                }
              >
                重新按分段组合
              </button>
            </div>
          )}
          {!!(d.content.generation_dependencies?.length||d.content.previous_image_dependencies?.length)&&<p className="notice">批次预览会附加固定的前图连续性说明；最终发送文本请在授权预览中核对。修改生图包后需重新预览。</p>}
          <textarea
            aria-label="最终完整提示词"
            className="final-prompt"
            rows={9}
            value={d.content.prompt || ""}
            onChange={(e) =>
              d.setContent({
                ...d.content,
                prompt: e.target.value,
                prompt_mode: "override",
              })
            }
          />
          <details>
            <summary>执行参数、依赖与检查要求</summary>
            {[
              ["parameters", "执行参数"],
              ["dependencies", "连续性说明（文字，不添加前图引用）"],
              ["missing", "缺件与检查目标"],
            ].map(([k, label]) => (
              <label key={k}>
                <span>{label}</span>
                <textarea
                  aria-label={label}
                  placeholder={label}
                  value={d.content[k] || ""}
                  onChange={(e) =>
                    d.setContent({ ...d.content, [k]: e.target.value })
                  }
                />
              </label>
            ))}
          </details>
          <div className="actions">
            <button onClick={() => void d.save()}>保存生图包</button>
            <span className="muted">
              {d.dirty ? "有未保存修改" : "当前内容已保存"} · v{record.version}
            </span>
          </div>
        </>
      )}
    </article>
  );
}
function BoundScript({
  pid,
  id,
  version,
}: {
  pid: string;
  id?: string;
  version?: number;
}) {
  const [r, setR] = useState<RecordItem | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    if (id)
      api<RecordItem>(base(pid) + `/records/${id}?version=${version}`)
        .then(setR)
        .catch((e) => setError(e.message));
  }, [id, version]);
  return (
    <>
      <ErrorNote message={error} />
      <p className="read-copy">{r?.content.description || "尚未绑定脚本"}</p>
      <p>{r?.content.dialogue}</p>
    </>
  );
}
export function Scripts(
  props: ProductionProps & { kind: "script" | "package" },
) {
  const { records, pid, kind, batch, episode } = props;
  const [generationResults,setGenerationResults] = useState(false);
  const [imageBatches,setImageBatches] = useState(false);
  const [query, setQuery] = useViewState(`${pid}:${kind}:query`, ""),
    [scope, setScope] = useViewState(
      `${pid}:${kind === "package" ? "package:table-scope" : "script:scope"}`,
      kind === "package" ? "range" : "episode",
    ),
    [rangeStart, setRangeStart] = useViewState(
      `${pid}:package:range-start`,
      Math.floor((episode - 1) / 5) * 5 + 1,
    ),
    [rangeEnd, setRangeEnd] = useViewState(
      `${pid}:package:range-end`,
      Math.floor((episode - 1) / 5) * 5 + 5,
    ),
    [packageStatus, setPackageStatus] = useState("all"),
    [selected, setSelected] = useViewState<string[]>(
      `${pid}:${kind}:table-selection`,
      [],
    ),
    [imageBasis,setImageBasis]=useState<RecordItem|null>(null),
    [range, setRange] = useState(false),
    [detail, setDetail] = useState<RecordItem | null>(null),
    [discuss, setDiscuss] = useState(false),
    [compare, setCompare] = useState<RecordItem | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const tableRef = useRef<HTMLDivElement>(null);
  const reviewBodyRef=useRef<HTMLDivElement>(null);
  const packageOrigin=useRef<string|null>(null);
  const scrollKey = `comic-script-scroll:${pid}:${kind}`;
  useEffect(() => {
    let value;
    try {
      value = JSON.parse(localStorage.getItem(scrollKey) || "null");
    } catch {
      return;
    }
    if (tableRef.current && value) {
      tableRef.current.scrollTop = value.top;
      tableRef.current.scrollLeft = value.left;
    }
  }, []);
  const all = records.filter((r) => r.kind === kind && primaryRecord(r));
  const inScope = (r: RecordItem) =>
    scope === "range"
      ? r.content.episode >= rangeStart && r.content.episode <= rangeEnd
      : scope === "all" || scope === "batch"
        ? scope === "all" || r.content.batch === batch
        : r.content.episode === episode;
  const rows = all
    .filter(
      (r) =>
        inScope(r) &&
        (kind !== "package" ||
          packageStatus === "all" ||
          (packageStatus === "missing" && !r.content.prompt?.trim()) ||
          (packageStatus === "candidate" &&
            records.some(
              (x) =>
                x.content.candidate_for === r.id && !x.content.adopted_into && !x.content.rejected,
            )) ||
          (packageStatus === "stale" &&
            records.some(
              (x) =>
                x.id === r.content.script_id &&
                x.version !== r.content.script_version,
            ))) &&
        (!query ||
          Object.values(r.content).join(" ").includes(query) ||
          String(r.content.panel) === query),
    )
    .sort(
      (a, b) =>
        a.content.episode - b.content.episode ||
        a.content.panel - b.content.panel,
    );
  const picked = all.filter((r) => selected.includes(r.id));
  const candidates = (r: RecordItem) =>
    records.filter(
      (x) => x.content.candidate_for === r.id && !x.content.adopted_into && !x.content.rejected,
    );
  const toggle = (id: string) =>
    setSelected((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : [...s, id],
    );
  const action = async (fn: () => Promise<any>) => {
    try {
      setBusy(true);
      setError("");
      await fn();
      await props.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={`production-review ${kind}-review`}>
      <div className="actions"><button onClick={()=>setGenerationResults(true)}>查看生成候选</button>{kind==="package"&&<button disabled={busy} onClick={()=>setImageBatches(true)}>批量图像任务</button>}</div>
      {generationResults && <GroupResults pid={pid} refresh={props.refresh} onClose={()=>setGenerationResults(false)}/>}
      <div className="review-toolbar">
        <div className="actions">
          <Select
            aria-label={kind === "package" ? "生图包显示范围" : "脚本显示范围"}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setSelected([]);
            }}
          >
            {kind === "package" && <option value="range">指定话范围</option>}
            <option value="episode">当前话</option>
            <option value="batch">当前10话</option>
            <option value="all">全项目</option>
          </Select>
          {kind === "package" && scope === "range" && (
            <div className="package-range-controls">
              <label>
                起始话
                <input
                  type="number"
                  min={1}
                  value={rangeStart}
                  onChange={(e) => {
                    const start = Math.max(1, +e.target.value);
                    setRangeStart(start);
                    setRangeEnd(start + 4);
                    setSelected([]);
                  }}
                />
              </label>
              <span>—</span>
              <label>
                结束话
                <input
                  type="number"
                  min={rangeStart}
                  value={rangeEnd}
                  onChange={(e) => {
                    setRangeEnd(Math.max(rangeStart, +e.target.value));
                    setSelected([]);
                  }}
                />
              </label>
            </div>
          )}
          {kind === "package" && (
            <Select
              aria-label="生图包状态"
              value={packageStatus}
              onChange={(e) => {
                setPackageStatus(e.target.value);
                setSelected([]);
              }}
            >
              <option value="all">全部状态</option>
              <option value="missing">缺少提示词</option>
              <option value="candidate">有修改候选</option>
              <option value="stale">脚本已更新</option>
            </Select>
          )}
          <input
            aria-label="查找话格内容"
            placeholder="查找角色、场景、格号或内容"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="actions">
          {kind === "script" ? (
            <button className="primary" onClick={() => setRange(true)}>
              从细纲选择话范围生成
            </button>
          ) : (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  const scripts = records.filter(
                    (r) =>
                      r.kind === "script" &&
                      primaryRecord(r) &&
                      inScope(r) &&
                      !all.some(
                        (p) =>
                          p.content.episode === r.content.episode &&
                          p.content.panel === r.content.panel,
                      ),
                  );
                  if (!scripts.length)
                    throw Error(
                      "当前范围没有待补齐的生图包；已有包可选中后讨论修改。",
                    );
                  await submitJob(pid, "package", scripts);
                  setNotice(`已提交范围内 ${scripts.length} 格缺失生图包`);
                })
              }
            >
              补齐范围内生图包
            </button>
          )}
        </div>
      </div>
      <ErrorNote message={error} />
      {notice && <div className="notice">{notice}</div>}
      {picked.length > 0 && (
        <div className="selection-bar">
          <strong>
            已选 {picked.length} 格
            {picked.some((r) => !rows.some((x) => x.id === r.id)) &&
              `（${picked.filter((r) => !rows.some((x) => x.id === r.id)).length} 格不在当前筛选中）`}
          </strong>
          <button onClick={() => setSelected([])}>清空选择</button>
          {kind === "script" && (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await api(
                    base(pid) + "/production-review",
                    json("POST", {
                      refs: picked.map((r) => ({
                        id: r.id,
                        version: r.version,
                      })),
                      decision: "approved",
                      note: "逐格审核通过",
                    }),
                  );
                  setNotice("选中版本已记录审核；模拟内容不能正式放行");
                })
              }
            >
              通过所选版本
            </button>
          )}
          <button onClick={() => setDiscuss(true)}>讨论并修改选中格</button>
          {kind==="package"&&<><button disabled={busy} onClick={()=>setImageBatches(true)}>{`批量图像预览（${picked.length}格）`}</button></>}
          {kind==="package"&&<button className="primary" disabled={picked.length!==1||busy} onClick={()=>setImageBasis(picked[0])}>{picked.length===1?"模型生图（单格预览）":"模型生图 · 请只选1格"}</button>}
          {kind === "script" ? (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await submitJob(pid, "package", picked);
                  setNotice("选中格生图包已排队");
                })
              }
            >
              生成所选生图包
            </button>
          ) : (
            <button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  const ready = picked.filter((r) => r.content.prompt?.trim());
                  if (!ready.length) throw Error("所选格都缺少完整提示词");
                  await submitJob(pid, "image", ready);
                  setNotice(
                    `已提交${ready.length}格；${picked.length - ready.length}格缺少提示词未提交`,
                  );
                })
              }
            >
              生成所选图片 · 模拟
            </button>
          )}
        </div>
      )}
      <div ref={reviewBodyRef} className="review-body" hidden={!rows.length}>
      {kind === "script" ? (
        <>
          <div className="table-guidance">
            <span>共 {rows.length} 格 · 横向滚动查看完整脚本11列</span>
            <span>点击格号放大阅读，勾选后审核或修改</span>
          </div>
          <div
            className="script-table-scroll"
            ref={tableRef}
            onScroll={(e) =>
              localStorage.setItem(
                scrollKey,
                JSON.stringify({
                  top: e.currentTarget.scrollTop,
                  left: e.currentTarget.scrollLeft,
                }),
              )
            }
          >
            <table className="full-script-table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="选择当前显示全部格"
                      checked={
                        rows.length > 0 &&
                        rows.every((r) => selected.includes(r.id))
                      }
                      onChange={(e) =>
                        setSelected(
                          e.target.checked ? rows.map((r) => r.id) : [],
                        )
                      }
                    />
                  </th>
                  {scriptFields.map(([k, l]) => (
                    <th key={k}>{l}</th>
                  ))}
                  <th>审核 / 候选</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <ScriptRows
                    key={r.id}
                    r={r}
                    first={
                      !i || rows[i - 1].content.episode !== r.content.episode
                    }
                    selected={selected.includes(r.id)}
                    toggle={() => toggle(r.id)}
                    open={() => {
                      props.onLocation(r.content.episode, r.content.panel);
                      setDetail(r);
                    }}
                    candidates={candidates(r).length}
                    compare={() => setCompare(r)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <PackageTable
          storageKey={`comic-package-table:${pid}`}
          rows={rows}
          records={records}
          selected={selected}
          setSelected={setSelected}
          open={(r) => {
            packageOrigin.current=r.id;
            props.onLocation(r.content.episode, r.content.panel);
            setDetail(r);
          }}
          compare={setCompare}
        />
      )}
      </div>
      {!rows.length && (
        <Empty
          title={
            all.length
              ? "当前条件下没有匹配的话格"
              : kind === "script" ? "从细纲开始生成成品脚本" : "本范围尚无生图包"
          }
          action={all.length > 0 && <button onClick={() => {
            setQuery("");
            setPackageStatus("all");
            setScope("all");
          }}>清除筛选，查看全部话</button>}
        >
          {all.length
            ? "换个关键词、话范围或状态，或清除筛选查看全部话。"
            : kind === "script"
              ? "选定起止话，生成后在这里连续审阅；无需逐格手工创建。"
              : "先在脚本审核中选择话格，再生成对应生图包。"}
        </Empty>
      )}
      {imageBatches&&<ImageBatches key={pid} pid={pid} packages={picked} records={records} refresh={props.refresh} onClose={()=>setImageBatches(false)}/>}
      {imageBasis&&<ImageGeneration key={imageBasis.id+":"+imageBasis.version} pid={pid} kind="image" basis={imageBasis} records={records} refresh={props.refresh} onClose={()=>setImageBasis(null)}/>}
      {range && (
        <RangeGeneration
          pid={pid}
          records={records}
          refresh={props.refresh}
          onClose={() => setRange(false)}
        />
      )}{" "}
      {detail && kind === "package" && (
        <Drawer
          title={`第${detail.content.episode}话 · 第${detail.content.panel}格生图包`}
          wide
          onClose={() => {
            const origin=packageOrigin.current,current=detail.id;
            setDetail(null);
            requestAnimationFrame(()=>{
              const buttons=Array.from(reviewBodyRef.current?.querySelectorAll<HTMLButtonElement>('button[data-package-open]')||[]);
              (buttons.find(b=>b.dataset.packageOpen===origin)||buttons.find(b=>b.dataset.packageOpen===current))?.focus();
            });
          }}
        >
          <div className="package-detail-nav">
            <button
              disabled={rows.findIndex((r) => r.id === detail.id) <= 0}
              onClick={() => {
                const r = rows[rows.findIndex((r) => r.id === detail.id) - 1];
                setDetail(r);
                props.onLocation(r.content.episode, r.content.panel);
              }}
            >
              上一格
            </button>
            <span>关闭后返回原表格位置与选择</span>
            <button
              disabled={
                rows.findIndex((r) => r.id === detail.id) >= rows.length - 1
              }
              onClick={() => {
                const r = rows[rows.findIndex((r) => r.id === detail.id) + 1];
                setDetail(r);
                props.onLocation(r.content.episode, r.content.panel);
              }}
            >
              下一格
            </button>
          </div>
          <PackageDetail
            key={detail.id}
            {...props}
            record={records.find((r) => r.id === detail.id) || detail}
          />
        </Drawer>
      )}
      {detail && kind === "script" && (
        <ScriptDetail
          key={detail.id}
          record={records.find((r) => r.id === detail.id) || detail}
          onSaved={props.onSaved}
          onClose={() => setDetail(null)}
        />
      )}
      {discuss && (
        <Drawer
          title={`修改选中的 ${picked.length} 格`}
          onClose={() => setDiscuss(false)}
        >
          <Conversation
            key={picked.map((r) => r.id).sort().join(",")}
            pid={pid}
            refs={picked}
            operation="rewrite"
            refresh={props.refresh}
          />
        </Drawer>
      )}
      {compare && (
        <CandidateReview
          record={records.find((r) => r.id === compare.id) || compare}
          candidates={candidates(compare)}
          onSaved={(r) => {
            props.onSaved(r);
            void props.refresh();
          }}
          onClose={() => setCompare(null)}
        />
      )}
    </div>
  );
}
function ScriptRows({
  r,
  first,
  selected,
  toggle,
  open,
  candidates,
  compare,
}: {
  r: RecordItem;
  first: boolean;
  selected: boolean;
  toggle: () => void;
  open: () => void;
  candidates: number;
  compare: () => void;
}) {
  return (
    <>
      {first && (
        <tr className="episode-heading">
          <th colSpan={13}><div className="episode-heading-content">
            第{r.content.episode}话 ·{" "}
            {r.content.episode_title || "话标题未标注"}
            <span>原著范围：{r.content.source_range || "未标注"}</span></div>
          </th>
        </tr>
      )}
      <tr className={selected ? "row-selected" : ""}>
        <td>
          <input
            type="checkbox"
            aria-label={`选择第${r.content.episode}话第${r.content.panel}格`}
            checked={selected}
            onChange={toggle}
          />
        </td>
        {scriptFields.map(([k]) => (
          <td key={k} className={"field-" + k}>
            {k === "panel" ? (
              <button onClick={open}>
                {r.content.episode}话 /{" "}
                {String(r.content.panel).padStart(2, "0")}格
              </button>
            ) : (
              r.content[k] || "—"
            )}
          </td>
        ))}
        <td>
          <span>
            {reviewLabel(r.review)} · v{r.version}
          </span>
          <Badge source={r.source} />
          {candidates > 0 && (
            <button onClick={compare}>比较 {candidates} 个候选</button>
          )}
        </td>
      </tr>
    </>
  );
}
