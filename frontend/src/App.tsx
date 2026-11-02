import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Layers3,
  FolderOpen,
  Settings2,
  PanelRight,
  Activity,
  ArrowLeft,
  Plus,
  Archive,
  ArrowUpRight,
  ChevronRight,
  CheckCircle2,
  FileText,
  Network,
  PenLine,
  Palette,
  Boxes,
  Clapperboard,
  Package,
  Images as ImagesIcon,
  ScanLine,
  MoreHorizontal,
  RotateCcw,
} from "lucide-react";
import { api, base, json, type Project, type RecordItem } from "./api";
import { Empty, ErrorNote, Busy, Drawer } from "./ui";
import {
  Original,
  Memory,
  Documents,
  Assets,
  type WorkspaceProps,
} from "./Preparation";
import { Scripts } from "./Production";
import { Images } from "./Images";
import { Tasks, Settings, ContextPanel } from "./Auxiliary";
const prep = [
  ["original", "小说原著", BookOpen, "导入与阅读，建立故事的唯一来源"],
  ["memory", "理解与记忆", Network, "查看人物、事件和关系依据"],
  ["skeleton", "改编骨架", PenLine, "组织全书结构与叙事节奏"],
  ["outline", "分集细纲", FileText, "把故事推进落实到每一话"],
  ["style", "画风与代表资产", Palette, "比较视觉方向，确认代表样例"],
  ["asset", "全面资产与确认", Boxes, "整理全书人物、场景和道具状态"],
] as const;
const production = [
  ["script", "逐格脚本", Clapperboard, "把每一话拆解为可执行的画面"],
  ["package", "逐格生图包", Package, "对照脚本、镜头、参考与直接提示词"],
  ["images", "生成与审图", ImagesIcon, "查看图片、版本和逐图问题"],
  ["modify", "人工修改", ScanLine, "标记局部目标，调整整体画面"],
] as const;

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]),
    [pid, setPid] = useState(""),
    [records, setRecords] = useState<RecordItem[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [name, setName] = useState(""),
    [archived, setArchived] = useState(false),
    [flow, setFlow] = useState("prep"),
    [stage, setStage] = useState("original"),
    [batch, setBatch] = useState(1),
    [episode, setEpisode] = useState(1),
    [panel, setPanel] = useState(1),
    [aux, setAux] = useState(""),
    [notice, setNotice] = useState(""),
    [gates, setGates] = useState<any>(null),
    [taskCount, setTaskCount] = useState(0),
    [rename, setRename] = useState(""),
    [connected, setConnected] = useState(true);
  const main = useRef<HTMLElement>(null),
    scroll = useRef<Record<string, number>>({}),
    activePid = useRef(pid), activeBatch=useRef(batch);
  activePid.current = pid;activeBatch.current=batch;
  const loadProjects = useCallback(async () => {
    try {
      setProjects(await api<Project[]>("/projects"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void loadProjects();
  }, []);
  const refresh = useCallback(async () => {
    if (!pid) return;
    const target = pid;
    const [rows, g, t] = await Promise.all([
      api<RecordItem[]>(base(pid) + "/records"),
      api(base(pid) + "/gates?batch=" + batch),
      api<any[]>(base(pid) + "/tasks"),
    ]);
    if (activePid.current !== target || activeBatch.current!==batch) return;
    setConnected(true);
    setRecords(rows);
    setGates(g);
    setTaskCount(
      t.filter((x: any) => ["queued", "running"].includes(x.status)).length,
    );
  }, [pid, batch]);
  useEffect(() => {
    if (!pid) return;
    setLoading(true);
    refresh()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    let previous = "";
    const t = setInterval(async () => {
      try {
        const tasks = await api<any[]>(base(pid) + "/tasks");
        if (activePid.current !== pid) return;
        setConnected(true);
        const signature = tasks.map((t) => t.id + ":" + t.status).join("|");
        setTaskCount(
          tasks.filter((t) => ["queued", "running"].includes(t.status)).length,
        );
        if (signature !== previous) {
          previous = signature;
          await refresh();
        }
      } catch {
        setConnected(false);
      }
    }, 1500);
    return () => clearInterval(t);
  }, [pid,batch]);
  useEffect(() => {
    if (pid)
      api(base(pid) + "/gates?batch=" + batch)
        .then(setGates)
        .catch(() => {});
  }, [pid, batch]);
  const onSaved = (r: RecordItem) => {
    if (r.project_id !== activePid.current) return;
    api(base(r.project_id) + "/gates?batch=" + activeBatch.current)
      .then(setGates)
      .catch(() => {});
    setRecords((prev) =>
      prev.some((x) => x.id === r.id)
        ? prev.map((x) => (x.id === r.id ? r : x))
        : [...prev, r],
    );
  };
  const run = async (
    kind: string,
    target?: RecordItem,
    extra: Record<string, any> = {},
  ) => {
    try {
      if (kind === "image" && !target)
        target = records.find(
          (r) =>
            r.kind === "image" &&
            r.content.batch === (extra.batch || batch) &&
            r.content.episode === (extra.episode || episode) &&
            r.content.panel === (extra.panel || Math.max(1, panel)),
        );
      await api(
        base(pid) + "/tasks",
        json("POST", {
          kind,
          ...(target
            ? { target_id: target.id, input_version: target.version }
            : {}),
          batch,
          episode,
          panel: Math.max(1, panel),
          ...extra,
        }),
      );
      setNotice("模拟任务已排队；可继续编辑，在任务中心查看进度。");
      await refresh();
      setTimeout(() => setNotice(""), 6000);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const confirmTrial = async () => {
    try {
      const images = records.filter(
        (r) => r.kind === "image" && r.content.episode === 1,
      );
      if (!images.length) {
        setError("请先导入或模拟生成第一话图片，再确认试制。");
        return;
      }
      const trial = await api<RecordItem>(
        base(pid) + "/records",
        json("POST", {
          kind: "trial",
          title: "首话试制确认",
          content: {
            references: images.map((r) => ({
              id: r.id,
              version: r.adopted,
              purpose: "首话试制采用版本",
            })),
            note: "人工确认当前第一话采用图片",
          },
        }),
      );
      await api(
        base(pid) + `/records/${trial.id}/reviews`,
        json("POST", {
          version: trial.version,
          decision: "approved",
          note: "确认首话试制采用版本；模拟图片仅记录模拟确认",
        }),
      );
      await refresh();
      setNotice("首话试制确认已记录；若使用模拟图片，则不满足正式放行条件。");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const open = (p: Project) => {
    setPid(p.id);
    setRecords([]);
    setError("");
    setRename(p.name);
    try {
      const saved = JSON.parse(
        localStorage.getItem("comic-view:" + p.id) || "null",
      );
      if (saved) {
        setFlow(saved.flow);
        setStage(saved.stage);
        setBatch(saved.batch);
        setEpisode(saved.episode);
        setPanel(saved.panel);
        return;
      }
    } catch {}
    setFlow("prep");
    setStage("original");
    setBatch(1);
    setEpisode(1);
    setPanel(1);
  };
  useEffect(() => {
    if (pid)
      localStorage.setItem(
        "comic-view:" + pid,
        JSON.stringify({ flow, stage, batch, episode, panel }),
      );
  }, [pid, flow, stage, batch, episode, panel]);
  const navigate = (next: string, nextFlow = flow) => {
    scroll.current[`${pid}/${stage}`] = main.current?.scrollTop || 0;
    setStage(next);
    setFlow(nextFlow);
    requestAnimationFrame(() => {
      if (main.current)
        main.current.scrollTop = scroll.current[`${pid}/${next}`] || 0;
    });
  };
  const create = async () => {
    if (!name.trim()) return;
    try {
      const p = await api<Project>("/projects", json("POST", { name }));
      setName("");
      await loadProjects();
      open(p);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const changeProject = async (p: Project, updates: Partial<Project>) => {
    try {
      await api(
        "/projects/" + p.id,
        json("PUT", { name: p.name, archived: !!p.archived, ...updates }),
      );
      await loadProjects();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const project = projects.find((p) => p.id === pid);
  const steps = flow === "prep" ? prep : production;
  const current = steps.find((s) => s[0] === stage) || steps[0];
  const props: WorkspaceProps = { pid, records, onSaved, refresh, run };
  const productionProps = {
    ...props,
    batch,
    episode,
    panel,
    onPanel: setPanel,
    onLocation: (e: number, p: number) => {
      setEpisode(e);
      setPanel(p);
    },
  };
  if (!pid)
    return (
      <div className="library">
        <header className="library-header">
          <div className="brand">
            <span className="brand-mark">
              <Layers3 size={22} />
            </span>
            <strong>条漫 Agent</strong>
            <span className="local-indicator">本机工作台</span>
          </div>
          <button aria-label="模型设置" title="模型设置" onClick={() => setAux("settings")}>
            <Settings2 size={17} />
            模型设置
          </button>
        </header>
        <main className="library-content">
          <div className="library-intro">
            <div>
              <div className="breadcrumb">创作空间</div>
              <h1>从故事，到每一格。</h1>
              <p>整理原著与资产，推进制作，让每个画面都有依据。</p>
            </div>
            <span className="library-illustration">
              <BookOpen size={76} strokeWidth={1} />
              <span>STORY → PANELS</span>
            </span>
          </div>
          <div className="library-toolbar">
            <div className="tabs">
              <button
                className={!archived ? "selected" : ""}
                onClick={() => setArchived(false)}
              >
                我的项目
              </button>
              <button
                className={archived ? "selected" : ""}
                onClick={() => setArchived(true)}
              >
                已归档
              </button>
            </div>
            <form
              className="actions"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <input
                aria-label="新项目名称"
                placeholder="输入新项目名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
              />
              <button className="primary" disabled={!name.trim()}>
                <Plus size={17} />
                新建项目
              </button>
            </form>
          </div>
          {!connected && (
            <div className="notice error" role="status">
              本地服务已断开。当前编辑保留在浏览器草稿中，请启动服务后重试保存。
            </div>
          )}
          <ErrorNote message={error} />
          {loading ? (
            <Busy />
          ) : projects.filter((p) => !!p.archived === archived).length ? (
            <div className="project-list">
              <div className="project-list-heading">
                <span>项目名称</span>
                <span>最近更新</span>
                <span>操作</span>
              </div>
              {projects
                .filter((p) => !!p.archived === archived)
                .map((p) => (
                  <div className="project-row" key={p.id}>
                    <button className="project-name" onClick={() => open(p)}>
                      <span className="project-icon">
                        <BookOpen size={22} />
                      </span>
                      <div>
                        <strong>{p.name}</strong>
                        <small>全书前期准备 / 批次制作</small>
                      </div>
                      <ArrowUpRight size={18} />
                    </button>
                    <span className="muted">
                      {new Date(p.updated).toLocaleDateString("zh-CN")}
                    </span>
                    <button
                      onClick={() =>
                        void changeProject(p, { archived: !p.archived })
                      }
                    >
                      {p.archived ? (
                        <RotateCcw size={16} />
                      ) : (
                        <Archive size={16} />
                      )}{" "}
                      {p.archived ? "恢复" : "归档"}
                    </button>
                  </div>
                ))}
            </div>
          ) : (
            <Empty
              title={archived ? "没有已归档项目" : "你的第一部作品，从这里开始"}
            >
              在上方填写项目名称。原著、草稿、参考图和审阅记录都将保存在本机。
            </Empty>
          )}
          <div className="library-bottom">
            <div>
              <BookOpen size={19} />
              <strong>全书前期准备</strong>
              <p>原著 → 骨架与细纲 → 画风与资产</p>
            </div>
            <div>
              <Clapperboard size={19} />
              <strong>每 10 话制作</strong>
              <p>逐格脚本 → 生图包 → 审图与修改</p>
            </div>
            <div>
              <CheckCircle2 size={19} />
              <strong>真实保存，清晰来源</strong>
              <p>基础操作可用 · AI 生成明确模拟</p>
            </div>
          </div>
        </main>
        <footer>
          条漫 Agent · 本地版本 0.1 <span>资料留在本机 · AI 尚未接入</span>
        </footer>
        {aux === "settings" && <Settings onClose={() => setAux("")} />}
      </div>
    );
  return (
    <div className="app">
      <aside className="sidebar">
        <button
          className="brand"
          aria-label="返回项目库"
          onClick={() => {
            setPid("");
            void loadProjects();
          }}
        >
          <span className="brand-mark">
            <Layers3 size={21} />
          </span>
          <strong>条漫 Agent</strong>
        </button>
        <button
          className="back-library"
          onClick={() => {
            setPid("");
            void loadProjects();
          }}
        >
          <ArrowLeft size={15} />
          项目库
        </button>
        <div className="project-switch">
          <small>当前项目</small>
          <strong>{project?.name}</strong>
          <button aria-label="项目选项" onClick={() => setAux("project")}>
            <MoreHorizontal size={18} />
          </button>
        </div>
        <div className="flow-nav">
          <button
            className={flow === "prep" ? "active" : ""}
            onClick={() => navigate("original", "prep")}
          >
            <BookOpen size={18} />
            全书前期准备
            <ChevronRight size={14} />
          </button>
          <button
            className={flow === "production" ? "active" : ""}
            onClick={() => navigate("script", "production")}
          >
            <Clapperboard size={18} />
            批次制作
            <ChevronRight size={14} />
          </button>
        </div>
        <div className="nav-label">
          {flow === "prep" ? "前期流程" : "制作流程"}
        </div>
        <nav aria-label="工作阶段">
          {steps.map(([id, label, Icon], i) => (
            <button
              key={id}
              aria-label={`${i+1} ${label}`}
              title={label}
              className={stage === id ? "active" : ""}
              onClick={() => navigate(id)}
            >
              <span className="step-number">{i + 1}</span>
              <Icon size={16} />
              <span>{label}</span>
              {records.some((r) => r.kind === id) && (
                <span className="nav-dot" />
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span
              className="green-dot"
              style={connected ? undefined : { background: "var(--error)" }}
            />
            <div>
              {connected?"本地服务已连接":"本地服务已断开"}<small>AI 能力 · 模拟模式</small>
            </div>
          </div>
          <button aria-label="任务中心" title="任务中心" onClick={() => setAux("tasks")}>
            <Activity size={17} />
            任务中心
            {taskCount > 0 && <span className="count">{taskCount}</span>}
          </button>
          <button aria-label="模型设置" title="模型设置" onClick={() => setAux("settings")}>
            <Settings2 size={17} />
            模型设置
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            {project?.name}
            <ChevronRight size={13} />
            {flow === "prep"
              ? "全书前期准备"
              : `第 ${(batch - 1) * 10 + 1}–${batch * 10} 话制作`}
            <ChevronRight size={13} />
            <strong>{current[1]}</strong>
          </div>
          <div className="actions">
            <span className="local-indicator">本机保存</span>
            <button onClick={() => setAux("context")}>
              <PanelRight size={17} />
              上下文资料
            </button>
          </div>
        </header>
        <main className="workspace" ref={main}>
          <div className="page-heading">
            <div>
              <div className="breadcrumb">
                {flow === "prep" ? "全书前期准备" : "批次制作"} /{" "}
                {steps.findIndex((s) => s[0] === stage) + 1} of {steps.length}
              </div>
              <h1>{current[1]}</h1>
              <p>{current[3]}</p>
            </div>
            <div className="stage-mark">
              {(() => {
                const Icon = current[2];
                return <Icon size={32} strokeWidth={1.2} />;
              })()}
            </div>
          </div>
          {flow === "production" && (
            <div className="batch-bar">
              <label>
                批次
                <select
                  aria-label="当前批次"
                  value={batch}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setBatch(n);
                    setEpisode((n - 1) * 10 + 1);
                    setPanel(1);
                  }}
                >
                  {Array.from(
                    {
                      length: Math.max(
                        5,
                        batch,
                        ...records.map((r) => r.content.batch || 1),
                      ),
                    },
                    (_, i) => (
                      <option key={i} value={i + 1}>
                        第 {i * 10 + 1}–{i * 10 + 10} 话
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label>
                当前话
                <select
                  aria-label="当前话"
                  value={episode}
                  onChange={(e) => {
                    setEpisode(Number(e.target.value));
                    setPanel(1);
                  }}
                >
                  {Array.from({ length: 10 }, (_, i) => (
                    <option key={i} value={(batch - 1) * 10 + i + 1}>
                      第 {(batch - 1) * 10 + i + 1} 话
                    </option>
                  ))}
                </select>
              </label>
              <label>
                格号
                <input
                  aria-label="当前格号"
                  type="number"
                  min={1}
                  value={Math.max(1, panel)}
                  onChange={(e) =>
                    setPanel(Math.max(1, Number(e.target.value)))
                  }
                />
              </label>
              <button
                onClick={() => {
                  const n =
                    Math.max(
                      batch,
                      ...records.map((r) => r.content.batch || 1),
                    ) + 1;
                  setBatch(n);
                  setEpisode((n - 1) * 10 + 1);
                  setPanel(1);
                }}
              >
                <Plus size={14} />
                新批次
              </button>
              <span className="muted">切换阶段保留当前话格</span>
            </div>
          )}
          {!connected && (
            <div className="notice error" role="status">
              本地服务已断开。当前编辑保留在浏览器草稿中，请启动服务后重试保存。
            </div>
          )}
          <ErrorNote message={error} />
          {error && <button onClick={() => setError("")}>收起提示</button>}
          {notice && (
            <div className="notice success" role="status">
              {notice}
            </div>
          )}
          {loading ? (
            <Busy />
          ) : (
            <div className="workspace-content">
              {stage === "original" && <Original {...props} />}{" "}
              {stage === "memory" && <Memory {...props} />}{" "}
              {(stage === "skeleton" || stage === "outline") && (
                <Documents key={stage} {...props} kind={stage} />
              )}{" "}
              {(stage === "style" || stage === "asset") && (
                <Assets key={stage} {...props} kind={stage} />
              )}{" "}
              {(stage === "script" || stage === "package") && (
                <Scripts
                  key={`${stage}-${batch}-${episode}`}
                  {...productionProps}
                  kind={stage}
                />
              )}{" "}
              {(stage === "images" || stage === "modify") && (
                <Images
                  key={`${stage}-${batch}`}
                  {...productionProps}
                  modify={stage === "modify"}
                />
              )}
            </div>
          )}
          {(stage === "asset" || flow === "production") && (
            <details className="gate-details">
              <summary>
                <CheckCircle2 size={16} />
                正式生产条件 · {gates?.reasons?.length || 0} 项待完成
                <span>查看缺件</span>
              </summary>
              <div>
                <p>{gates?.reasons?.join("、") || "业务条件已满足"}。</p>
                <p>真实模型尚未接入；模拟审核不会满足正式放行条件。</p>
                <div className="actions">
                  <button onClick={() => void confirmTrial()}>
                    确认首话试制采用版本
                  </button>
                  <span>
                    已有 {records.filter((r) => r.kind === "trial").length}{" "}
                    条确认记录
                  </span>
                </div>
                {stage === "script" && (
                  <button
                    onClick={() =>
                      void run("script", undefined, { fail: true })
                    }
                  >
                    演示一次失败任务
                  </button>
                )}
              </div>
            </details>
          )}
        </main>
        <footer className="statusbar">
          <span>
            本机工作区 <span className="separator">/</span>{" "}
            {flow === "prep"
              ? "全书范围"
              : `第 ${episode} 话 · 第 ${Math.max(1, panel)} 格`}
          </span>
          <span>基础操作真实保存 · AI 结果明确模拟</span>
        </footer>
      </div>
      {aux === "tasks" && (
        <Tasks
          pid={pid}
          onClose={() => setAux("")}
          onChanged={() => void refresh()}
        />
      )}{" "}
      {aux === "settings" && <Settings onClose={() => setAux("")} />}{" "}
      {aux === "context" && (
        <ContextPanel records={records} onClose={() => setAux("")} />
      )}{" "}
      {aux === "project" && (
        <Drawer title="项目设置" onClose={() => setAux("")}>
          <label>
            项目名称
            <input value={rename} onChange={(e) => setRename(e.target.value)} />
          </label>
          <div className="actions">
            <button onClick={() => setAux("")}>取消</button>
            <button
              className="primary"
              onClick={async () => {
                if (project) {
                  await changeProject(project, { name: rename });
                  setAux("");
                }
              }}
            >
              保存名称
            </button>
          </div>
        </Drawer>
      )}
    </div>
  );
}
