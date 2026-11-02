import { useEffect, useState, useRef } from "react";
import { api, base, json, RecordItem } from "./api";
import { Drawer, ErrorNote, Badge } from "./ui";
import {
  parseOutline,
  OutlineEntry,
  scriptFields,
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
  pid,
  records,
  onClose,
  refresh,
}: {
  pid: string;
  records: RecordItem[];
  onClose: () => void;
  refresh: () => Promise<void>;
}) {
  const outlines = records.filter(
    (r) => r.kind === "outline" && !r.content.pending_for,
  );
  const [id, setId] = useState(outlines.at(-1)?.id || "");
  const outline = outlines.find((r) => r.id === id);
  const [entries, setEntries] = useState<OutlineEntry[]>([]),
    [index, setIndex] = useState<RecordItem | null>(null),
    [start, setStart] = useState(1),
    [end, setEnd] = useState(1),
    [instruction, setInstruction] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
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
    <Drawer title="从细纲生成完整逐格脚本" onClose={onClose}>
      <p>
        选择原著对应的细纲版本，核对话号和段落，再指定起止话。已有脚本请使用选格修改。
      </p>
      <ErrorNote message={error} />
      {notice && <div className="notice">{notice}</div>}
      <label>
        细纲版本
        <select value={id} onChange={(e) => setId(e.target.value)}>
          {outlines.map((r) => (
            <option key={r.id} value={r.id}>
              {r.title} · v{r.version}
            </option>
          ))}
        </select>
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
        模拟将每话返回3格结构样例，不代表真实成品质量。输入会冻结原著、骨架和所选细纲版本。
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
              onClose();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在提交…" : `模拟生成第 ${start}–${end} 话`}
        </button>
      </div>
    </Drawer>
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
      <select
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
      </select>
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
export function Conversation({
  pid,
  refs,
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
  const key = refs
    .map((r) => r.id + ":" + r.version)
    .sort()
    .join(",");
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
  const [showResults, setShowResults] = useViewState(
    "result-open:" +
      pid +
      refs
        .map((r) => r.id)
        .sort()
        .join(","),
    false,
  );
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
    api<RecordItem[]>(base(pid) + "/conversations").then((rows) =>
      setChat(
        rows.find(
          (r) =>
            r.content.refs
              .map((v: any) => v.id + ":" + v.version)
              .sort()
              .join(",") === key,
        ) || null,
      ),
    );
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [key]);
  return (
    <section className="conversation">
      <header>
        <h3>{refs.length > 1 ? `${refs.length} 格共同修改` : "批注与对话"}</h3>
        <span className="muted">讨论后再生成 · 明确模拟</span>
      </header>
      <ErrorNote message={error} />
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
      <div className="chat-messages">
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
      </button>
      <div className="generation-plan">
        <h4>本次修改方案</h4>
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
        <p className="muted">
          {operation === "repair"
            ? "会汇总各图已保存的区域批注及保护区。"
            : "只修改所选格，保留格号和身份。"}{" "}
          结果保存为候选，由你比较采用。
        </p>
        <button
          className="primary"
          disabled={
            busy ||
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
          {busy ? "正在提交…" : "按方案生成 · 模拟"}
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
function GroupResults({
  pid,
  groups,
  refresh,
  onClose,
}: {
  pid: string;
  groups: string[];
  refresh: () => Promise<void>;
  onClose: () => void;
}) {
  const [tasks, setTasks] = useState<any[]>([]),
    [outputs, setOutputs] = useState<Record<string, RecordItem>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = async () => {
    const rows = await api<any[]>(base(pid) + "/tasks?compact=true");
    const chosen = rows
      .filter((t) => groups.includes(t.payload.group_id))
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
          async (t) =>
            [
              t.output_id,
              await api<RecordItem>(base(pid) + "/records/" + t.output_id),
            ] as const,
        ),
    );
    setTasks(chosen);
    setOutputs(Object.fromEntries(results));
  };
  useEffect(() => {
    void load().catch((e) => setError(e.message));
    const timer = setInterval(
      () => void load().catch((e) => setError(e.message)),
      1500,
    );
    return () => clearInterval(timer);
  }, [groups.join(",")]);
  return (
    <Drawer title="本组修改结果 · 逐格比较采用" wide onClose={onClose}>
      <p>同组候选集中展示；只采用你确认的格，其他格保持原稿。</p>
      <ErrorNote message={error} />
      {!tasks.length && <p>正在读取任务…</p>}
      {tasks.map((t) => {
        const out = outputs[t.output_id],
          original = t.payload.snapshots?.[0];
        return (
          <section className="group-result" key={t.id}>
            <div className="detail-heading">
              <h3>
                第{t.payload.episode}话 · 第{t.payload.panel}格
              </h3>
              <span>
                {(
                  {
                    queued: "排队中",
                    running: "生成中",
                    succeeded: "候选已生成",
                    failed: "失败",
                    interrupted: "已中断",
                  } as any
                )[t.status] || t.status}
              </span>
            </div>
            <p className="muted">本次要求：{t.payload.instruction}</p>
            {out &&
              original &&
              (out.kind === "image" ? (
                <div className="candidate-images">
                  {[original, out].map((r, i) => (
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
                  {[original, out].map((r, i) => (
                    <section key={i}>
                      <h4>{i ? "修改候选" : "原稿 v" + r.version}</h4>
                      {(out.kind === "script"
                        ? scriptFields.slice(1)
                        : [["prompt", "完整提示词"]]
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
            {out && (
              <button
                className="primary"
                disabled={busy || !!out.content.adopted_into}
                onClick={async () => {
                  try {
                    setBusy(true);
                    await api(
                      base(pid) + "/candidates/" + out.id + "/adopt",
                      json("POST", {}),
                    );
                    await load();
                    await refresh();
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {out.content.adopted_into ? "此格已采用" : "采用此格候选"}
              </button>
            )}
            {["failed", "interrupted"].includes(t.status) && (
              <>
                <p>{t.error}</p>
                <button
                  disabled={busy}
                  onClick={async () => {
                    try {
                      setBusy(true);
                      await api(
                        base(pid) + "/tasks/" + t.id + "/retry",
                        json("POST", {}),
                      );
                      await load();
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  仅重试此格
                </button>
              </>
            )}
          </section>
        );
      })}
    </Drawer>
  );
}
