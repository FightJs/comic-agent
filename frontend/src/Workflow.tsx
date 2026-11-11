import {ToolReceiptRecovery,needsToolReceiptRecovery} from './ToolReceiptRecovery';
import {PauseToCheckpoint} from './PauseToCheckpoint';
import {ProductionContinuation} from "./ProductionContinuation";
import {AgentPanel} from "./AgentPanel";
import { documentText } from "./documentContent";
import { Select } from "./Select";
import { useEffect, useState, useRef } from "react";
import { api, base, json, RecordItem } from "./api";
import { Drawer, ErrorNote, Badge } from "./ui";
import {
  parseOutline,
  OutlineEntry,
  scriptFields,
  promptFields,
  primaryRecord,
  clearSubmittedMessage,
} from "./workflowLogic";
import { useViewState } from "./useViewState";
export async function submitJob(
  pid: string,
  operation: string,
  refs: RecordItem[],
  extra: Record<string, any> = {},
  submission = crypto.randomUUID(),
) {
  for (const r of refs) {
    if (localStorage.getItem(`comic-draft:${pid}:${r.id}`))
      throw new Error(
        `第${r.content.episode || 1}话第${r.content.panel || 1}格仍有未保存编辑，请保存成功后再生成`,
      );
  }
  return api(
    base(pid) + "/production-jobs",
    json("POST", {
      operation,
      refs: refs.map((r) => ({ id: r.id, version: r.version })),
      submission_id: submission,
      ...extra,
    }),
  );
}
export function RangeGeneration({
  initialOutlineId,
  pid,
  records,
  onClose,
  refresh,
}: {
  pid: string;
  initialOutlineId?: string;
  records: RecordItem[];
  onClose: () => void;
  refresh: () => Promise<void>;
}) {
  const outlines = records.filter(
    (r) => r.kind === "outline" && primaryRecord(r),
  );
  const [id, setId] = useState(initialOutlineId || outlines.at(-1)?.id || "");
  const outline = outlines.find((r) => r.id === id);
  const [entries, setEntries] = useState<OutlineEntry[]>([]),
    [index, setIndex] = useState<RecordItem | null>(null),
    [start, setStart] = useState(1),
    [end, setEnd] = useState(1),
    [instruction, setInstruction] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [results,setResults] = useState(false);
  const token = useRef(crypto.randomUUID());
  useEffect(() => {
    if (!outline) return;
    let active = true;
    api<RecordItem | null>(base(pid) + "/outline-index/" + id)
      .then((r) => {
        if (!active) return;
        setIndex(r);
        const e =
          r?.content.outline_version === outline.version
            ? r.content.entries
            : parseOutline(outline.content.html || "");
        setEntries(e);
        setStart(e[0]?.episode || 1);
        setEnd(e.at(-1)?.episode || 1);
        setNotice(
          r && r.content.outline_version !== outline.version
            ? "细纲已改稿，请重新校正并保存话索引"
            : "",
        );
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
    };
  }, [id]);
  const save = async () => {
    if (!outline) throw Error("请先建立细纲");
    const skeleton = records.filter(r => r.kind === "skeleton").at(-1);
    for (const input of [outline, skeleton]) {
      if (input && localStorage.getItem(`comic-draft:${pid}:${input.id}`)) throw Error("骨架或所选细纲仍有未保存编辑，请保存成功后再生成脚本。");
    }
    const r = await api<RecordItem>(
      base(pid) + "/outline-index/" + id,
      json("PUT", {
        outline_version: outline.version,
        expected_version: index?.version || 0,
        entries,
      }),
    );
    setIndex(r);
    return r;
  };
  return (
    <>
    <Drawer title="从细纲生成完整逐格脚本" onClose={onClose}>
      <p>
        选择原著对应的细纲版本，核对话号和段落，再指定起止话。已有脚本请使用选格修改。
      </p>
      <ErrorNote message={error} />
      {notice && <div className="notice">{notice}</div>}
      <label>
        细纲版本
        <Select value={id} onChange={(e) => setId(e.target.value)}>
          {outlines.map((r) => (
            <option key={r.id} value={r.id}>
              {r.title} · v{r.version}
            </option>
          ))}
        </Select>
      </label>
      {!outlines.length && <p>请先到全书前期建立细纲。</p>}
      <div className="range-controls">
        <label>
          起始话
          <input
            type="number"
            min="1"
            value={start}
            onChange={(e) => setStart(+e.target.value)}
          />
        </label>
        <label>
          结束话
          <input
            type="number"
            min="1"
            value={end}
            onChange={(e) => setEnd(+e.target.value)}
          />
        </label>
      </div>
      <details>
        <summary>查看原细纲全文</summary>
        <div className="read-copy">
          {
            new DOMParser().parseFromString(
              outline?.content.html || "",
              "text/html",
            ).body.textContent
          }
        </div>
      </details>
      <h3>话号与段落对应 · 可校正</h3>
      <p className="muted">
        标题识别只作初始建议。重复、缺话或空正文会阻止生成。保存索引不会改写原细纲。
      </p>
      {entries.map((entry, i) => (
        <details
          className="outline-entry"
          key={i}
          open={
            entry.episode >= start && entry.episode <= end && entries.length < 4
          }
        >
          <summary>
            第{entry.episode}话 · {entry.title}
            {entry.episode >= start && entry.episode <= end
              ? " · 已选范围"
              : ""}
          </summary>
          <label>
            话号
            <input
              type="number"
              value={entry.episode}
              onChange={(e) =>
                setEntries(
                  entries.map((v, n) =>
                    n === i ? { ...v, episode: +e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <label>
            话标题
            <input
              value={entry.title}
              onChange={(e) =>
                setEntries(
                  entries.map((v, n) =>
                    n === i ? { ...v, title: e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <label>
            对应细纲
            <textarea
              rows={5}
              value={entry.text}
              onChange={(e) =>
                setEntries(
                  entries.map((v, n) =>
                    n === i ? { ...v, text: e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <label>
            原著范围
            <input
              placeholder="未标注时留空"
              value={entry.source_range}
              onChange={(e) =>
                setEntries(
                  entries.map((v, n) =>
                    n === i ? { ...v, source_range: e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <button onClick={() => setEntries(entries.filter((_, n) => i !== n))}>
            移除此映射
          </button>
        </details>
      ))}
      <button
        onClick={() =>
          setEntries([
            ...entries,
            {
              episode: (entries.at(-1)?.episode || 0) + 1,
              title: "新话",
              text: "",
              source_range: "",
            },
          ])
        }
      >
        添加话映射
      </button>
      <label>
        本次生成要求
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="节奏、单格限制或需特别注意的连续性"
        />
      </label>
      <p className="notice">
        将调用已配置的文本模型，按实际输出生成格数。输入冻结原著、骨架、细纲和流程版本；结果需逐格核对采用。
      </p>
      <div className="actions">
        <button
          disabled={busy}
          onClick={async () => {
            try {
              setBusy(true);
              await save();
              setNotice("索引已保存");
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          保存索引
        </button>
        <button
          className="primary"
          disabled={busy || !outline}
          onClick={async () => {
            try {
              setBusy(true);
              setError("");
              const idx = await save();
              await submitJob(
                pid,
                "range",
                [],
                {
                  outline_id: id,
                  outline_version: outline!.version,
                  index_version: idx.version,
                  start,
                  end,
                  instruction,
                },
                token.current,
              );
              await refresh();
              setResults(true);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在提交…" : `生成第 ${start}–${end} 话候选`}
        </button>
      </div>
    </Drawer>
    {results && <GroupResults pid={pid} groups={[token.current]} refresh={refresh} onClose={() => {setResults(false);onClose();}}/>}
    </>
  );
}
export function CandidateReview({
  record,
  candidates,
  onSaved,
  onClose,
}: {
  record: RecordItem;
  candidates: RecordItem[];
  onSaved: (r: RecordItem) => void;
  onClose: () => void;
}) {
  const [error, setError] = useState(""),
    [chosen, setChosen] = useState(candidates.at(-1)?.id || "");
  const candidate = candidates.find((r) => r.id === chosen);
  return (
    <Drawer title="比较修改候选" onClose={onClose}>
      <ErrorNote message={error} />
      <Select
        aria-label="候选结果"
        value={chosen}
        onChange={(e) => setChosen(e.target.value)}
      >
        {candidates.map((r) => (
          <option value={r.id} key={r.id}>
            {r.title} · {new Date(r.created).toLocaleString()}{" "}
            {r.content.adopted_into ? "已采用" : ""}
          </option>
        ))}
      </Select>
      <p>
        原稿 v{record.version}；候选基于 v{candidate?.content.input_version}
        。采用后旧稿仍保留。
      </p>
      {candidate && (
        <>
          <Badge source={candidate.source} />
          {record.kind === "image" ? (
            <div className="candidate-images">
              <figure>
                <img src={record.content.url} alt="原图" />
                <figcaption>原图</figcaption>
              </figure>
              <figure>
                <img src={candidate.content.url} alt="候选图" />
                <figcaption>模拟候选</figcaption>
              </figure>
            </div>
          ) : (
            <div className="candidate-text">
              {[record, candidate].map((r, i) => (
                <section key={r.id}>
                  <h3>{i ? "候选" : "原稿"}</h3>
                  {(record.kind === "script"
                    ? scriptFields
                    : [["prompt", "完整提示词"]]
                  ).map(([key, label]) => (
                    <div key={key}>
                      <strong>{label}</strong>
                      <p>{r.content[key] || "—"}</p>
                    </div>
                  ))}
                </section>
              ))}
            </div>
          )}
          <button
            className="primary"
            disabled={!!candidate.content.adopted_into}
            onClick={async () => {
              try {
                onSaved(
                  await api(
                    base(record.project_id) +
                      "/candidates/" +
                      candidate.id +
                      "/adopt",
                    json("POST", {}),
                  ),
                );
                onClose();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            采用此候选
          </button>
        </>
      )}
    </Drawer>
  );
}
export function Conversation(props:Parameters<typeof ConversationBody>[0]) {
  const scope=props.refs.map(r=>r.id+(props.operation==='repair'?":"+r.version:"")).sort().join(",");
  return <ConversationBody key={props.pid+"/"+props.operation+"/"+scope} {...props}/>;
}
function ConversationBody({
  pid,
  refs: currentRefs,
  operation,
  refresh,
  annotationsReady = true,
  annotationRevision = "",
}: {
  pid: string;
  refs: RecordItem[];
  operation: "rewrite" | "repair";
  refresh: () => Promise<void>;
  annotationsReady?: boolean;
  annotationRevision?: string;
}) {
  const [openedRefs] = useState(currentRefs);
  const refs = operation === 'rewrite' ? openedRefs : currentRefs;
  const stale = operation === 'rewrite' && refs.some(ref => currentRefs.find(r => r.id === ref.id)?.version !== ref.version);
  const key = refs
    .map((r) => r.id + ":" + r.version)
    .sort()
    .join(",");
  const [historyChats, setHistoryChats] = useState<RecordItem[]>([]);
  const [chat, setChat] = useState<RecordItem | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [draft, setDraft] = useViewState("discussion:" + pid + key, ""),
    [plan, setPlan] = useViewState("plan:" + pid + key, ""),
    [perItem, setPerItem] = useViewState<Record<string, string>>(
      "per-item:" + pid + key,
      {},
    );
  const [planRuns,setPlanRuns]=useViewState<string[]>("plan-runs:"+pid+key,[]);
  const [annotationRefresh, setAnnotationRefresh] = useState(0);
  const [annotationPreview, setAnnotationPreview] = useState<
    Record<string, { version: number; items: any[] }>
  >({});
  const [groups, setGroups] = useViewState<string[]>(
    "result-groups:" +
      pid +
      refs
        .map((r) => r.id)
        .sort()
        .join(","),
    [],
  );
  const [showResults, setShowResults] = useState(false);
  useEffect(() => {
    if (operation !== "repair") return;
    let alive = true;
    setAnnotationPreview({});
    Promise.all(
      refs.map(
        async (r) =>
          [
            r.id,
            await api(
              recPathLocal(r) + `/annotations?image_version=${r.version}`,
            ),
          ] as const,
      ),
    )
      .then((rows) => {
        if (alive) setAnnotationPreview(Object.fromEntries(rows));
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [key, annotationRevision, annotationsReady, annotationRefresh]);
  const token = useRef(crypto.randomUUID());
  const load = () =>
    api<RecordItem[]>(base(pid) + "/conversations").then((rows) => {
      const ids = refs
        .map((r) => r.id)
        .sort()
        .join(",");
      const matching = rows.filter(
        (r) =>
          r.content.refs
            .map((v: any) => v.id)
            .sort()
            .join(",") === ids,
      );
      const same = (r: RecordItem) =>
        r.content.refs
          .map((v: any) => v.id + ":" + v.version)
          .sort()
          .join(",") === key;
      setChat(operation==="rewrite"?null:matching.find(same) || null);
      setHistoryChats(operation==="rewrite"?matching:matching.filter((r) => !same(r)));
    });
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [key]);
  return (
    <section className="conversation">
      <header>
        <h3>{refs.length > 1 ? `${refs.length} 格共同修改` : "批注与对话"}</h3>
        <span className="muted">{operation==="rewrite"?"Pi 讨论 · 明确加入方案后再生成":"图片讨论与返修仍为模拟"}</span>
      </header>
      <ErrorNote message={error} />
      {stale && <p className="notice" role="status">底稿已有新版本，当前讨论、暂停记录和输入仍绑定打开时的版本。请保留所需意见，关闭后重新打开以使用新底稿；当前不能按旧方案生成。</p>}
      {error && (
        <button
          onClick={() => {
            setAnnotationRefresh((v) => v + 1);
            void load()
              .then(() => setError(""))
              .catch((e) => setError(e.message));
          }}
        >
          重新读取对话与批注（保留输入）
        </button>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {groups.length > 0 && (
        <button
          className="group-result-button"
          onClick={() => setShowResults(true)}
        >
          查看本组修改结果 · 连续比较
        </button>
      )}
      {historyChats.length > 0 && (
        <details className="history-discussions">
          <summary>查看历史底稿讨论 · {historyChats.length} 组</summary>
          {historyChats.map((r) => (
            <details key={r.id}>
              <summary>
                {r.content.refs
                  .map((v: any) => {
                    const item = refs.find((x) => x.id === v.id);
                    return `${item?.content.episode}话${item?.content.panel}格 v${v.version}`;
                  })
                  .join(" / ")}
              </summary>
              <p className="muted">历史讨论只读，不会加入当前生成方案。</p>
              {r.content.messages.map((m: any) => (
                <article className={"message " + m.role} key={m.id}>
                  <strong>{m.role === "user" ? "你" : "模拟助手"}</strong>
                  <p>{m.text}</p>
                </article>
              ))}
            </details>
          ))}
        </details>
      )}
      {operation==='rewrite'?<AgentPanel key={key} pid={pid} stage={refs[0]?.kind==='package'?'package':'script'} records={currentRefs} boundRefs={refs.map(r=>({id:r.id,version:r.version}))} onChanged={refresh} onUseReply={reply=>{
        if(planRuns.includes(reply.id)){setNotice('此回复已加入方案；可直接编辑方案。');return;}
        const next=[plan,reply.reply].filter(Boolean).join('\n');
        if(next.length>20000){setError('加入后超过20000字，请先精简方案或自行摘录建议。');return;}
        setPlan(next);setPlanRuns([...planRuns,reply.id]);setNotice('已加入生成方案，尚未启动生成。');
      }}/>:<><div className="chat-messages">
        {!chat && (
          <p className="muted">
            先描述希望如何修改，可以讨论和补充。发送消息不会启动生成。
          </p>
        )}
        {chat?.content.messages.map((m: any) => (
          <article key={m.id} className={"message " + m.role}>
            <strong>{m.role === "user" ? "你" : "模拟助手"}</strong>
            <p>{m.text}</p>
          </article>
        ))}
      </div>
      <label>
        讨论修改建议
        <textarea
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="例如：这几格保持同一个房间，让窗户与人物站位一致…"
        />
      </label>
      <button
        disabled={busy || !draft.trim()}
        onClick={async () => {
          try {
            setBusy(true);
            setError("");
            const next = await api<RecordItem>(
              base(pid) + "/conversations",
              json("POST", {
                refs: refs.map((r) => ({ id: r.id, version: r.version })),
                message: draft,
                expected_version: chat?.version || 0,
              }),
            );
            setChat(next);
            setDraft((current) => clearSubmittedMessage(current, draft));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        发送讨论消息
      </button></>}
      <div className="generation-plan">
        <h4>本次修改方案</h4>
        {operation==='rewrite'&&planRuns.length>0&&<p className="muted">已引用 {planRuns.length} 条完成的AI回复；生成时核对项目和话格版本。<button onClick={()=>{setPlan('');setPlanRuns([]);setNotice('已清空方案和AI引用。');}}>清空方案及AI引用</button></p>}
        {chat && (
          <button
            onClick={() =>
              setPlan((current) =>
                [current, chat.content.plan].filter(Boolean).join("\n"),
              )
            }
          >
            将最新意见加入方案
          </button>
        )}
        <label>
          共同要求 / 整图要求
          <textarea
            rows={4}
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            placeholder="可从讨论整理或直接填写；只有下方按钮会启动生成"
          />
        </label>
        <details className="per-item-plans" open={refs.length <= 5}>
          <summary>逐格补充与输入版本 · {refs.length} 格（按需展开）</summary>
          {refs.map((r) => (
            <details key={r.id}>
              <summary>
                第{r.content.episode}话 · 第{r.content.panel}格 · 底稿 v
                {r.version}
              </summary>
              {r.kind === "image" && (
                <img
                  className="plan-thumbnail"
                  src={r.content.url}
                  alt="本次底图"
                />
              )}
              {operation === "repair" && (
                <div className="annotation-preview">
                  <small>
                    批注版本 {annotationPreview[r.id]?.version ?? "读取中"}
                  </small>
                  {annotationPreview[r.id]?.items.map((a: any, i: number) => (
                    <p key={a.id}>
                      {i + 1}. {a.type === "protect" ? "保护区" : "修改区域"}：
                      {a.note || "未填写文字"}
                    </p>
                  ))}
                </div>
              )}
              <label>
                该格补充意见
                <textarea
                  rows={2}
                  value={perItem[r.id] || ""}
                  onChange={(e) =>
                    setPerItem({ ...perItem, [r.id]: e.target.value })
                  }
                />
              </label>
            </details>
          ))}
        </details>
        <p className="muted">
          {operation === "repair"
            ? "会汇总各图已保存的区域批注及保护区。"
            : "只修改所选格，保留格号和身份。"}{" "}
          结果保存为候选，由你比较采用。
        </p>
        <button
          className="primary"
          disabled={
            busy || stale ||
            !plan.trim() ||
            !annotationsReady ||
            (operation === "repair" &&
              refs.some((r) => !annotationPreview[r.id]))
          }
          onClick={async () => {
            try {
              setBusy(true);
              setError("");
              await submitJob(
                pid,
                operation,
                refs,
                {
                  instruction: plan,
                  per_item: perItem,
                  annotation_versions: Object.fromEntries(
                    Object.entries(annotationPreview).map(([id, a]) => [
                      id,
                      a.version,
                    ]),
                  ),
                  ...(operation==="rewrite"?{agent_run_ids:planRuns}:{}),
                  ...(chat
                    ? {
                        conversation_id: chat.id,
                        conversation_version: chat.version,
                      }
                    : {}),
                },
                token.current,
              );
              setGroups([...groups, token.current]);
              setShowResults(true);
              token.current = crypto.randomUUID();
              setNotice(`已提交 ${refs.length} 格，候选完成后可比较采用`);
              await refresh();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在提交…" : (["image","repair"].includes(operation) ? "按方案生成 · 模拟" : "按方案生成候选")}
        </button>
        {!annotationsReady && (
          <small>区域批注尚未保存，保存完成后可生成。</small>
        )}
      </div>
      {showResults && (
        <GroupResults
          pid={pid}
          groups={groups}
          refresh={refresh}
          onClose={() => setShowResults(false)}
        />
      )}
    </section>
  );
}

function recPathLocal(r: RecordItem) {
  return base(r.project_id) + "/records/" + r.id;
}
function CandidateError({message}:{message:string}) {
  const anchor=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(message)anchor.current?.scrollIntoView?.({block:'nearest'});},[message]);
  return message?<div ref={anchor} style={{scrollMarginBlockStart:120,scrollMarginBlockEnd:24}}><ErrorNote message={message}/></div>:null;
}

export function GroupResults({
  pid,
  groups = [],
  kindFilter,
  refresh,
  onClose,
}: {
  pid: string;
  groups?: string[];
  kindFilter?: string;
  refresh: () => Promise<void>;
  onClose: () => void;
}) {
  const [tasks, setTasks] = useState<any[]>([]),
    [outputs, setOutputs] = useState<Record<string, RecordItem>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded,setLoaded] = useState(false),
    [receipts,setReceipts] = useState<Record<string,any[]>>({}),
    [rowErrors,setRowErrors] = useState<Record<string,string>>({});
  const load = async () => {
    const rows = await api<any[]>(base(pid) + "/tasks?compact=true");
    const chosen = rows
      .filter((t) => groups.length ? groups.includes(t.payload.group_id) : ["range","rewrite","package","document"].includes(t.payload.operation))
      .filter(t=>!kindFilter || t.payload.kind===kindFilter)
      .flatMap((t) => (t.payload.output_ids?.length ? t.payload.output_ids : [t.output_id]).map((output_id: string) => ({...t,output_id})))
      .sort(
        (a, b) =>
          groups.indexOf(b.payload.group_id) -
            groups.indexOf(a.payload.group_id) ||
          a.payload.episode - b.payload.episode ||
          a.payload.panel - b.payload.panel,
      );
    const results = await Promise.all(
      chosen
        .filter((t) => t.output_id)
        .map(
          async (t) => {
            const version=t.payload.output_versions?.[t.output_id] || 1;
            const [frozen,head]=await Promise.all([
              api<RecordItem>(base(pid)+"/records/"+t.output_id+"?version="+version),
              api<RecordItem>(base(pid)+"/records/"+t.output_id),
            ]);
            const adopted=head.content.adopted_into || (frozen.content.creation_candidate && !head.content.creation_candidate ? {id:head.id,version:head.adopted} : undefined);
            return [t.output_id,{...frozen,content:{...frozen.content,adopted_into:adopted,rejected:head.content.rejected,candidate_changed:!adopted && !head.content.rejected && head.version!==version}}] as const;
          }
        ),
    );
    setTasks(chosen);
    setLoaded(true);
    setOutputs(Object.fromEntries(results));
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
    const timer = setInterval(
      () => void load().catch((e) => setError(e.message)),
      1500,
    );
    return () => clearInterval(timer);
  }, [groups.join(","),kindFilter]);
  const documentsOnly=!!kindFilter && ['skeleton','outline'].includes(kindFilter) || tasks.length>0 && tasks.every(t=>t.payload.operation==='document');
  return (
    <Drawer title={documentsOnly ? '文档生成结果 · 比较采用' : groups.length ? "本组修改结果 · 逐格比较采用" : "生成候选 · 逐格核对采用"} wide onClose={onClose}>
      <p>{documentsOnly?'生成结果先保留为候选；核对原稿与新稿后明确采用，其他文档保持不变。':'同组候选集中展示；只采用你确认的格，其他格保持原稿。'}</p>
      <ErrorNote message={error} />
      {!tasks.length && <p>{loaded ? "尚无文本生成任务。请先从细纲生成脚本，或对已选话格生成候选。" : "正在读取任务…"}</p>}
      {tasks.map((t) => {
        const out = outputs[t.output_id],
          original = t.payload.operation === 'package' ? t.payload.existing_package || t.payload.snapshots?.[0] : t.payload.snapshots?.[0],
          subject=['skeleton','outline'].includes(out?.kind || t.payload.kind)?'文档':'此格';
        return (
          <section className="group-result" id={"production-result-"+t.id} tabIndex={-1} key={t.id + ":" + t.output_id}>
            <div className="detail-heading">
              <h3>
                {t.payload.operation==='document' ? (t.payload.document_kind==='skeleton'?'全书骨架':'分集细纲') : `第${out?.content.episode || t.payload.episode}话 · 第${out?.content.panel || t.payload.panel}格`}
                <small className="muted"> · {({document:'文档生成',range:'脚本生成',rewrite:'文本修改',package:'生图包生成',image:'模拟生图',repair:'模拟返修'} as any)[t.payload.operation]}{t.created?' · '+new Date(t.created).toLocaleString('zh-CN'):''}</small>
              </h3>
              <span>
                {(['queued','running'].includes(t.status)&&t.pause_requested)?'正在暂停，等待收尾':t.status==='paused'&&t.payload.production_checkpoint?.reason==='manual_pause'?'已暂停':(
                  {
                    queued: "排队中",
                    running: "生成中",
                    succeeded: "候选已生成",
                    failed: "失败",
                    interrupted: "已中断",
                    cancelled: "已取消",
                    paused: "额度暂停",
                  } as any
                )[t.status] || t.status}
              </span>
            </div>
            <p className="muted">本次要求：{t.payload.instruction}</p>
            <Badge source={out?.source || t.source || t.payload.source || 'mock'}/>
            {out?.content.candidate_changed && <p className="notice">此候选已另行改稿，下面保留生成时正文。请拒绝旧候选并重新生成核对。</p>}
            {out?.content.input_stale && <p className="notice">生成期间输入已变化。此候选保留供比较，请核对最新输入后重新生成。</p>}
            {t.status==='paused'&&t.payload.production_checkpoint&&<ProductionContinuation key={pid+":"+t.payload.production_checkpoint.attempt_id} pid={pid} tid={t.id} checkpoint={t.payload.production_checkpoint} onChanged={load}/>}
            {['queued','running'].includes(t.status)&&t.payload.frozen&&['document','range','rewrite','package'].includes(t.payload.operation)&&<PauseToCheckpoint key={t.id} endpoint={base(pid)+`/production-jobs/${t.id}/pause`} requested={!!t.pause_requested} focusId={'production-checkpoint-'+t.id} fallbackId={'production-result-'+t.id} onChanged={load}/>}
            {["queued","running","paused"].includes(t.status) && <button disabled={busy} onClick={async()=>{try{setBusy(true);setRowErrors(v=>({...v,[t.id+":"+t.output_id]:""}));await api(base(pid)+`/production-jobs/${t.id}/cancel`,json('POST',{}));await load();}catch(e){setRowErrors(v=>({...v,[t.id+":"+t.output_id]:(e as Error).message}));}finally{setBusy(false);}}}>取消此任务</button>}
            {t.payload.frozen && <details onToggle={async e=>{if(!e.currentTarget.open)return;try{setReceipts(v=>({...v,[t.id]:[]}));const value=await api<any[]>(base(pid)+`/production-jobs/${t.id}/attempts`);setReceipts(v=>({...v,[t.id]:value}));}catch(e){setRowErrors(v=>({...v,[t.id+":"+t.output_id]:(e as Error).message}));}}}><summary>查看模型返回与用量</summary>{receipts[t.id]?.map((r,index)=><section key={r.id}><p>运行段{index+1} · 第{r.attempt}轮结构尝试 · {({paused:r.checkpoint?.reason==='manual_pause'?'手动暂停':'额度暂停',continued:'已续接，原段保留',queued:'等待续接',valid:'校验通过',invalid:'结构未通过',error:'调用未完成',interrupted:'应用重启，返回未确认',running:'运行中',received:'已返回'} as any)[r.status] || r.status} · {r.usage ? `输入 ${r.usage.input} / 输出 ${r.usage.output} tokens` : r.checkpoint?.usage ? `已知 ${r.checkpoint.usage.totalTokens} tokens；总用量仍未知` : '用量未知'}{r.continuation?.parent_id?' · 从上一段继续':''}</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{r.raw || '尚无可显示的模型返回'}</pre>{['failed','interrupted','paused'].includes(t.status)&&needsToolReceiptRecovery(r.status,r.checkpoint)&&!(t.status==='paused'&&t.payload.production_checkpoint?.attempt_id===r.id)&&<ToolReceiptRecovery cancelEndpoint={base(pid)+`/production-jobs/${t.id}/cancel`} endpoint={base(pid)+`/production-jobs/${t.id}/attempts/${r.id}`} focusId={'production-checkpoint-'+t.id} onChanged={async()=>{await load();const value=await api<any[]>(base(pid)+`/production-jobs/${t.id}/attempts`);setReceipts(v=>({...v,[t.id]:value}));}}/>}</section>)}</details>}

            {out?.kind==="package"&&out.content.prompt_mode==="override"&&<p className="notice">完整提示词覆盖模式：最终发送完整提示词，分段不会自动合成。如需影响生图，请明确修改完整提示词。</p>}
            {out &&
              (out.kind === "image" ? (
                <div className="candidate-images">
                  {[...(original ? [original] : []), out].map((r, i) => (
                    <figure key={i}>
                      <img
                        src={r.content.url}
                        alt={i ? "修改候选" : "原底图"}
                      />
                      <figcaption>
                        {i ? "模拟候选" : "原底图 v" + r.version}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              ) : (
                <div className="candidate-text">
                  {[...(original ? [original] : []), out].map((r, i) => (
                    <section key={i}>
                      <h4>{!original || i ? "修改候选" : t.payload.operation === "package" && r.kind === "script" ? "源脚本 v" + r.version : "原稿 v" + r.version}</h4>
                      {['skeleton','outline'].includes(r.kind) ? <div className="read-copy">{documentText(r.content)}</div> : (r.kind === "script"
                        ? scriptFields.slice(1)
                        : [...promptFields,["prompt", "完整提示词"]]
                      ).map(([k, l]) => (
                        <div key={k}>
                          <strong>{l}</strong>
                          <p>{r.content[k] || "—"}</p>
                        </div>
                      ))}
                    </section>
                  ))}
                </div>
              ))}
            <CandidateError message={rowErrors[t.id+":"+t.output_id] || ""}/>
            {out && (
              <button
                className="primary"
                disabled={busy || !!out.content.candidate_changed || !!out.content.rejected || !!out.content.adopted_into || (!out.content.creation_candidate && !out.content.candidate_for)}
                onClick={async () => {
                  try {
                    setBusy(true);setRowErrors(v=>({...v,[t.id+":"+t.output_id]:""}));
                    const ids = new Set([...Object.keys(t.payload.input_refs || {}), ...(out.content.candidate_for ? [out.content.candidate_for] : [])]);
                    if([...ids].some(id=>localStorage.getItem(`comic-draft:${pid}:${id}`)) || (t.payload.queried_graph_revision !== undefined && localStorage.getItem(`comic-graph-draft:${pid}`))) throw Error('输入或目标仍有未保存草稿，请先保存或处理草稿，再采用。');
                    await api(
                      base(pid) + "/candidates/" + out.id + "/adopt",
                      json("POST", {}),
                    );
                    await load();
                    await refresh();
                  } catch (e) {
                    setRowErrors(v=>({...v,[t.id+":"+t.output_id]:(e as Error).message}));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {out.content.candidate_changed ? "候选已改稿" : out.content.rejected ? `${subject}已拒绝` : out.content.adopted_into || (!out.content.creation_candidate && !out.content.candidate_for) ? `${subject}已采用` : `采用${subject}候选`}
              </button>
            )}
            {out && !out.content.rejected && !out.content.adopted_into && (out.content.creation_candidate || out.content.candidate_for) && <button disabled={busy} onClick={async()=>{try{setBusy(true);setRowErrors(v=>({...v,[t.id+":"+t.output_id]:""}));await api(base(pid)+`/candidates/${out.id}/reject`,json('POST',{}));await load();await refresh();}catch(e){setRowErrors(v=>({...v,[t.id+":"+t.output_id]:(e as Error).message}));}finally{setBusy(false);}}}>{`拒绝${subject}候选`}</button>}
            {["failed", "interrupted"].includes(t.status) && !t.payload.production_continuation && (
              <>
                <p>{t.error}</p>
                <button
                  disabled={busy}
                  onClick={async () => {
                    try {
                      setBusy(true);setRowErrors(v=>({...v,[t.id+":"+t.output_id]:""}));
                      await api(
                        base(pid) + "/tasks/" + t.id + "/retry",
                        json("POST", {}),
                      );
                      await load();
                    } catch (e) {
                      setRowErrors(v=>({...v,[t.id+":"+t.output_id]:(e as Error).message}));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t.payload.operation === "document" ? "重试此文档" : t.payload.operation === "range" ? "仅重试此话" : "仅重试此格"}
                </button>
              </>
            )}
          </section>
        );
      })}
    </Drawer>
  );
}
