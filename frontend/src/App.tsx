import { preparationGroup, preparationTabs } from "./preparationNavigation";
import { Select } from "./Select";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  MessageSquare,
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
  MoreHorizontal,
  RotateCcw,
} from "lucide-react";
import { api, base, json, type Project, type RecordItem } from "./api";
import { Empty, ErrorNote, Busy, Drawer } from "./ui";
import { AgentPanel, type AgentStage } from "./AgentPanel";
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
  ["original", "理解与记忆", BookOpen, "从小说原著出发，理解人物、事件和关系"],
  ["skeleton", "改编与细纲", PenLine, "组织全书骨架，将故事推进落实到每一话"],
  ["style", "画风与资产", Palette, "比较三版画风，确认后生成并审核全面资产"],
] as const;
const production = [
  ["script", "脚本审核", Clapperboard, "从细纲生成成品脚本，连续审阅并修改选中格"],
  ["package", "逐格生图包", Package, "对照脚本、镜头、参考与直接提示词"],
  ["images", "图片工作区", ImagesIcon, "在画面上批注，与 AI 讨论后生成修改候选"],
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
      api<any[]>(base(pid) + "/tasks?compact=true"),
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
        const tasks = await api<any[]>(base(pid) + "/tasks?compact=true");
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
        base(pid) + "/tasks?compact=true",
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
        setStage(saved.stage === "modify" ? "images" : saved.stage);
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
    if (pid && flow === "prep") {
      localStorage.setItem(`comic-prep-last:${pid}`, stage);
      localStorage.setItem(`comic-prep-tab:${pid}:${preparationGroup(stage)}`, stage);
    }
    if (pid)
      localStorage.setItem(
        "comic-view:" + pid,
        JSON.stringify({ flow, stage, batch, episode, panel }),
      );
  }, [pid, flow, stage, batch, episode, panel]);
  const navigate = (next: string, nextFlow = flow) => {
    scroll.current[`${pid}/${stage}`] = main.current?.scrollTop || 0;
    if (nextFlow === "prep") localStorage.setItem(`comic-prep-tab:${pid}:${preparationGroup(next)}`, next);
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
  const activeStage = flow === "prep" ? preparationGroup(stage) : stage;
  const current = steps.find((s) => s[0] === activeStage) || steps[0];
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
              <div className="library-caption"><span className="green-dot" /> 本地创作工作台</div>
              <h1>创作空间<span>原著、分镜与画面，集中在一处。</span></h1>
            </div>
            <div className="library-route" aria-label="创作流程">
              <span><BookOpen size={20} strokeWidth={1.5} /><strong>故事</strong><small>原著与改编</small></span>
              <ChevronRight size={16} />
              <span><Clapperboard size={20} strokeWidth={1.5} /><strong>分镜</strong><small>脚本与镜头</small></span>
              <ChevronRight size={16} />
              <span><ImagesIcon size={20} strokeWidth={1.5} /><strong>画面</strong><small>生成与审阅</small></span>
            </div>
          </div>
          <div className="library-toolbar">
            <div className="tabs" aria-label="项目分类">
              <button
                className={!archived ? "selected" : ""}
                aria-pressed={!archived}
                onClick={() => setArchived(false)}
              >
                我的项目
              </button>
              <button
                className={archived ? "selected" : ""}
                aria-pressed={archived}
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
                      <span className="project-icon" aria-hidden="true">
                        <BookOpen size={22} strokeWidth={1.5} />
                      </span>
                      <div>
                        <strong>{p.name}</strong>
                        <small>打开创作工作区 <ChevronRight size={12} /></small>
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
              <strong>批次制作</strong>
              <p>逐格脚本 → 生图包 → 审图与修改</p>
            </div>
            <div className="library-mode-note">
              <CheckCircle2 size={19} />
              <strong>安心留在本机</strong>
              <p>作品与记录本地保存。图谱、文本、单格图像、独立格批次与单图视觉复查可连接模型；前图依赖需采用审核后恢复；可选实图检查与一轮严重剧情返修；其他返修待接入。</p>
            </div>
          </div>
        </main>
        <footer>
          条漫 Agent · 本地版本 0.1 <span>资料本地保存 · 图谱可连接模型</span>
        </footer>
        {aux === "settings" && <Settings onClose={() => setAux("")} />}
      </div>
    );
  return (
    <div className={"app" + (flow === "production" ? " production-app" : "") + ((stage === "images" || stage === "modify") ? " image-mode" : "") + ((stage === "script" || stage === "package") ? " review-mode" : "")}>
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
          <small>正在创作</small>
          <strong>{project?.name}</strong>
          <button aria-label="项目选项" onClick={() => setAux("project")}>
            <MoreHorizontal size={18} />
          </button>
        </div>
        <div className="flow-nav">
          <button
            className={flow === "prep" ? "active" : ""}
            aria-pressed={flow === "prep"}
            onClick={() => navigate(localStorage.getItem(`comic-prep-last:${pid}`) || "original", "prep")}
          >
            <BookOpen size={18} />
            全书前期准备
            <ChevronRight size={14} />
          </button>
          <button
            className={flow === "production" ? "active" : ""}
            aria-pressed={flow === "production"}
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
              className={activeStage === id ? "active" : ""}
              aria-current={activeStage === id ? "page" : undefined}
              onClick={() => {
                const remembered = localStorage.getItem(`comic-prep-tab:${pid}:${id}`);
                navigate(flow === "prep" && remembered && preparationGroup(remembered) === id ? remembered : id);
              }}
            >
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
              {connected?"本地服务已连接":"本地服务已断开"}<small>单图、视觉与独立格批次可连接 · 前图依赖需审核恢复 · 可选检查/一轮剧情返修</small>
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
            {stage!=="images" && stage!=="modify" && <button onClick={()=>setAux("agent")}><MessageSquare size={16}/>AI 助手</button>}
            <button onClick={() => setAux("gates")} disabled={!gates}>
              <CheckCircle2 size={16} />
              {gates ? `生产条件 · ${gates.reasons?.length || 0}` : "正在读取条件"}
            </button>
            <button onClick={() => setAux("context")}>
              <PanelRight size={17} />
              上下文资料
            </button>
          </div>
        </header>
        <main className="workspace" ref={main}>
          <div className="page-heading">
            <div className="stage-heading-copy" title={current[3]}>
              <div className="stage-title-row">
                <h1>{current[1]}</h1>
                <div className="stage-position">
                  <span>{flow === "prep" ? "全书前期准备" : "批次制作"}</span>
                  <div className="stage-sequence" aria-label={`当前第 ${steps.findIndex((s) => s[0] === activeStage) + 1} 阶段，共 ${steps.length} 阶段`}>
                    {steps.map(([id]) => <span key={id} className={activeStage === id ? "current" : ""} />)}
                  </div>
                </div>
              </div>
              <p title={current[3]}>{current[3]}</p>
            </div>
          {flow === "production" && (
            <div className="batch-bar">
              <label>
                批次
                <Select
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
                </Select>
              </label>
              <label>
                当前话
                <Select
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
                </Select>
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
            </div>
          )}
          </div>
          {!connected && (
            <div className="notice error" role="status">
              本地服务已断开。当前编辑保留在浏览器草稿中，请启动服务后重试保存。
            </div>
          )}
          {flow === "prep" && <nav className="prep-tabs" aria-label="当前阶段功能">
            {preparationTabs[preparationGroup(stage)].map(([id, label]) => <button key={id} aria-pressed={stage === id} className={stage === id ? "active" : ""} onClick={() => navigate(id)}>{label}</button>)}
          </nav>}
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
                <Assets key={stage} {...props} kind={stage} onConfirmed={() => navigate("asset")} />
              )}{" "}
              {(stage === "script" || stage === "package") && (
                <Scripts
                  key={`${stage}-${batch}`}
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

        </main>
        <footer className="statusbar">
          <span>
            本机工作区 <span className="separator">/</span>{" "}
            {flow === "prep"
              ? "全书范围"
              : `第 ${episode} 话 · 第 ${Math.max(1, panel)} 格`}
          </span>
          <span>图谱与编辑真实保存 · 模拟创作明确标记</span>
        </footer>
      </div>
      {aux === "agent" && (
        <Drawer title={`${current[1]} · AI 助手`} onClose={()=>setAux("")}>
          <AgentPanel key={pid+stage} pid={pid} onChanged={refresh} onConfigure={()=>setAux("settings")} stage={(stage==="original"||stage==="memory"?"memory":stage==="assets"?"asset":stage) as AgentStage} records={records}/>
        </Drawer>
      )}
      {aux === "gates" && (
        <Drawer title="正式生产条件" onClose={() => setAux("")}>
            <p>{gates?.reasons?.join("、") || "业务条件已满足"}。</p>
            <p>图谱和文本创作可调用配置的模型；模拟依赖与模拟审核不会满足正式放行条件。</p>
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

        </Drawer>
      )}
      {aux === "tasks" && (
        <Tasks
          pid={pid}
          onClose={() => setAux("")}
          onChanged={() => void refresh()}
        />
      )}{" "}
      {aux === "settings" && <Settings pid={pid} onClose={() => setAux("")} />}{" "}
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
