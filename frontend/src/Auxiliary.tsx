import { SetupAssistant } from "./SetupAssistant";
import { ModelCapabilities } from "./ModelCapabilities";
import { SkillManager,hasSkillDraft } from "./SkillManager";
import { ProjectPreferenceSettings } from "./ProjectPreferences";
import { RuntimeCapacity } from "./RuntimeCapacity";
import { ConfigImport } from "./ConfigImport";
import { GraphJobs } from "./GraphDocuments";
import { Select } from "./Select";
import { useEffect, useState } from "react";
import { RefreshCw, Clock3, KeyRound } from "lucide-react";
import { api, base, json, type RecordItem } from "./api";
import { Badge, Drawer, Empty, ErrorNote } from "./ui";
export function Tasks({
  pid,
  onClose,
  onChanged,
}: {
  pid: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tasks, setTasks] = useState<any[]>([]),
    [error, setError] = useState(""),
    [filter, setFilter] = useState("all");
  useEffect(() => {
    const load = () =>
      api<any[]>(base(pid) + "/tasks")
        .then(setTasks)
        .catch((e) => setError(e.message));
    void load();
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [pid]);
  const status: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败",
    interrupted: "已中断",
    pending: "待处理回复",
    cancelled: "已取消",
  };
  return (
    <Drawer title="任务中心" onClose={onClose}>
      <div className="notice">
        小说图谱、骨架/细纲和逐格文本生产已调用配置的模型；画风、资产和逐格生图及实图复查需明确授权。旧图片批注讨论仍为模拟，候选来源单独标记，需明确采用。
      </div>
      <GraphJobs pid={pid} />
      <h3>创作任务</h3>
      <Select
        aria-label="任务状态筛选"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      >
        <option value="all">全部任务</option>
        {Object.entries(status).map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </Select>
      <ErrorNote message={error} />
      {tasks
        .filter((t) => filter === "all" || t.status === filter)
        .map((t) => (
          <div className="task" key={t.id}>
            <div className="task-heading">
              <Clock3 size={16} />
              <strong>
                {
                  (
                    {
                      memory: "理解与记忆",
                      skeleton: "全书骨架",
                      outline: "分集细纲",
                      script: "逐格脚本",
                      package: "生图包",
                      image: "生图",
                      repair: "修改复查",
                      asset: "资产",
                      style: "画风",
                    } as any
                  )[t.payload.kind]
                }
              </strong>
              <Badge source={t.source || "mock"} />
              <span className="status-text">{status[t.status]}</span>
            </div>
            <p>
              {t.error ||
                `输入版本 ${t.payload.input_version || "无"} · 第 ${t.payload.episode} 话 / ${t.payload.panel} 格`}
            </p>
            <small>{new Date(t.created).toLocaleString("zh-CN")}</small>
            {["failed", "interrupted"].includes(t.status) && (
              <button
                onClick={async () => {
                  try {
                    await api(base(pid) + `/tasks/${t.id}/retry`, {
                      method: "POST",
                    });
                    onChanged();
                  } catch (e) {
                    setError((e as Error).message);
                  }
                }}
              >
                <RefreshCw size={14} />
                重试原输入
              </button>
            )}
          </div>
        ))}
      {!tasks.length && (
        <Empty title="还没有任务">
          在当前阶段发起生成后，任务状态会显示在这里。
        </Empty>
      )}
    </Drawer>
  );
}
export function Settings({ onClose,pid }: { onClose: () => void;pid?:string }) {
  const [value, setValue] = useState<any>({
      url: "",
      model: "",
      purpose: "text",
    }),
    [secret, setSecret] = useState(""),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false),
    [baseline,setBaseline]=useState<any>(null),[assistant,setAssistant]=useState(false),[importWorking,setImportWorking]=useState(false),[skillEpoch,setSkillEpoch]=useState(0);
  const signature=(v:any)=>JSON.stringify([v.purpose||"text",v.url||"",v.model||"",v.api||((v.purpose===undefined||v.purpose==="text"||v.purpose==="vision")?"openai-completions":v.purpose==="image"?"openai-images":"mineru")]);
  const dirty=Boolean(secret)||(baseline!==null&&signature(value)!==signature(baseline)),blocked=busy||importWorking||baseline===null;
  function accept(v:any){setValue(v);setBaseline(v);}
  async function reload(){setBusy(true);try{accept(await api("/settings?purpose="+value.purpose));setSecret("");setSaved(false);setSkillEpoch(v=>v+1);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function switchPurpose(purpose:string){setBusy(true);setSaved(false);setError("");try{accept(await api("/settings?purpose="+purpose));setSecret("");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  useEffect(() => {
    api("/settings")
      .then(accept)
      .catch((e) => setError(e.message));
  }, []);
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api(
        "/settings",
        json("PUT", {
          url: value.url,
          model: value.model,
          purpose: value.purpose,
          ...(value.api ? {api:value.api} : {}),
          ...(secret ? { secret } : {}),
        }),
      );
      accept(r);
      setSecret("");
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer title="模型设置" onClose={onClose}>
      <section className="setup-entry"><h3>让AI帮助配置</h3><p>提供配置包或流程包，让助手核对缺项、用途和安装方案；逐项确认后才应用。</p><button className="primary" disabled={dirty||importWorking||baseline===null} onClick={()=>setAssistant(true)}>AI 配置与流程助手</button>{dirty&&<p className="notice">手动配置尚未保存，请先保存或还原，再使用助手或应用配置包。</p>}</section>
      <ConfigImport disabled={busy||dirty} onWorking={setImportWorking} onApplied={reload}/>
      <RuntimeCapacity/>
      {pid&&<details><summary>模型能力核对</summary><ModelCapabilities pid={pid} disabled={blocked||dirty}/></details>}
      {pid&&<ProjectPreferenceSettings pid={pid}/>}
      <details><summary>风格与流程 Skill</summary><SkillManager key={skillEpoch} pid={pid}/></details>
      <h3>手动配置</h3>
      <div className="notice">
        <KeyRound size={16} />
        文本配置用于AI助手及小说图谱。保存配置后，等待中的图谱任务会继续；单图及固定批次生图、实图检查与一轮严重剧情返修已连接模型，结果仍需人工采用和审核。
      </div>
      <ErrorNote message={error} />
      {value.vault_error && (
        <div className="notice error">{value.vault_error}</div>
      )}
      <label>
        服务地址
        <input
          disabled={blocked}
          value={value.url}
          placeholder={value.purpose === "parse" ? "https://mineru.net/api/v4" : "https://…/v1"}
          onChange={(e) => {
            setValue({ ...value, url: e.target.value });
            setSaved(false);
          }}
        />
      </label>
      <label>
        模型标识
        <input
          disabled={blocked}
          value={value.model}
          placeholder="填写供应商实际模型标识"
          onChange={(e) => {
            setValue({ ...value, model: e.target.value });
            setSaved(false);
          }}
        />
      </label>
      <label>
        用途
        <Select
          disabled={blocked||dirty}
          value={value.purpose}
          onChange={(e) => {
            void switchPurpose(e.target.value);
          }}
        >
          <option value="text">文本理解与编排</option>
          <option value="image">生图与修改</option>
          <option value="vision">看图检查</option>
          <option value="parse">PDF 解析 · MinerU</option>
        </Select>
      </label>
      {(value.purpose==="text"||value.purpose==="vision")&&<label>接口协议<Select disabled={blocked} value={value.api||"openai-completions"} onChange={e=>{setValue({...value,api:e.target.value});setSaved(false);}}><option value="openai-completions">OpenAI兼容 · Chat Completions</option><option value="openai-responses">OpenAI · Responses</option><option value="anthropic-messages">Anthropic · Messages</option></Select><small>按供应商实际协议选择；支持能力及真实效果须分别验证。</small></label>}
      <label>
        API 密钥
        <input
          disabled={blocked}
          type="password"
          autoComplete="new-password"
          value={secret}
          placeholder={
            value.has_secret
              ? "已存入钥匙串；留空保留"
              : "仅保存到 macOS 钥匙串"
          }
          onChange={(e) => {
            setSecret(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <p className="muted">
        浏览器不会读取已保存密钥。若钥匙串不可用，会明确报错，不回退到明文文件。
      </p>
      <button className="primary" disabled={blocked||!dirty} onClick={() => void save()}>
        {busy ? "保存中…" : "保存配置"}
      </button>
      {dirty&&<button disabled={blocked} onClick={()=>{setValue(baseline);setSecret("");setError("");setSaved(false);}}>还原已保存配置</button>}
      {assistant&&<SetupAssistant pid={pid} onApplied={reload} canApply={kind=>dirty?"手动配置有未保存修改，请先处理草稿。":kind==="select_skills"&&hasSkillDraft(pid)?"项目流程仍有未保存选择，请关闭助手后先保存或放弃草稿，再核对方案。":""} onClose={()=>{setAssistant(false);void reload();}}/>}
      {saved && (
        <p className="success" role="status">
          配置已保存 · 连接未验证，实际结果见对应任务或讨论
        </p>
      )}
    </Drawer>
  );
}
export function ContextPanel({
  records,
  onClose,
}: {
  records: RecordItem[];
  onClose: () => void;
}) {
  const [tab, setTab] = useState("original"),
    [query, setQuery] = useState("");
  const rows = records.filter((r) => r.kind === tab);
  return (
    <Drawer title="上下文资料" onClose={onClose}>
      <div className="tabs">
        {[
          ["original", "原著"],
          ["memory", "记忆"],
          ["asset", "资产"],
          ["package", "生图包"],
        ].map(([k, v]) => (
          <button
            key={k}
            className={k === tab ? "selected" : ""}
            onClick={() => setTab(k)}
          >
            {v}
          </button>
        ))}
      </div>
      <input
        placeholder="查找资料"
        aria-label="查找上下文资料"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {rows
        .filter(
          (r) =>
            !query ||
            JSON.stringify(r.content).includes(query) ||
            r.title.includes(query),
        )
        .map((r) => (
          <details key={r.id}>
            <summary>
              {r.title} <Badge source={r.source} />
            </summary>
            {r.content.url && r.kind !== "original" && (
              <img
                className="asset-detail-image"
                src={r.content.url}
                alt={r.title}
              />
            )}
            <pre className="text-preview">
              {r.content.text ||
                r.content.prompt ||
                JSON.stringify(r.content, null, 2)}
            </pre>
          </details>
        ))}
      {!rows.length && (
        <p className="muted">
          该类资料尚未建立。关闭面板后仍回到当前工作位置。
        </p>
      )}
    </Drawer>
  );
}
