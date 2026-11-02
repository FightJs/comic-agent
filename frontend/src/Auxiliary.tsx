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
  };
  return (
    <Drawer title="任务中心" onClose={onClose}>
      <div className="notice">
        本轮所有 AI 任务均为模拟；无真实费用、模型耗时和质量结论。
      </div>
      <select
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
      </select>
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
              <Badge source="mock" />
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
          在当前阶段发起模拟操作后，任务状态会显示在这里。
        </Empty>
      )}
    </Drawer>
  );
}
export function Settings({ onClose }: { onClose: () => void }) {
  const [value, setValue] = useState<any>({
      url: "",
      model: "",
      purpose: "text",
    }),
    [secret, setSecret] = useState(""),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/settings")
      .then(setValue)
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
          ...(secret ? { secret } : {}),
        }),
      );
      setValue(r);
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
      <div className="notice">
        <KeyRound size={16} />
        配置可保存，连接未验证；本轮不发送模型请求。
      </div>
      <ErrorNote message={error} />
      {value.vault_error && (
        <div className="notice error">{value.vault_error}</div>
      )}
      <label>
        服务地址
        <input
          value={value.url}
          placeholder="https://…/v1"
          onChange={(e) => {
            setValue({ ...value, url: e.target.value });
            setSaved(false);
          }}
        />
      </label>
      <label>
        模型标识
        <input
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
        <select
          value={value.purpose}
          onChange={(e) => {
            setSecret("");
            setSaved(false);
            api("/settings?purpose=" + e.target.value)
              .then(setValue)
              .catch((e) => setError(e.message));
          }}
        >
          <option value="text">文本理解与编排</option>
          <option value="image">生图与修改</option>
          <option value="vision">看图检查</option>
        </select>
      </label>
      <label>
        API 密钥
        <input
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
      <button className="primary" disabled={busy} onClick={() => void save()}>
        {busy ? "保存中…" : "保存配置"}
      </button>
      {saved && (
        <p className="success" role="status">
          配置已保存 · 连接未验证
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
