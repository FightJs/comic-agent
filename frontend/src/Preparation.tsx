import {AgentPanel} from "./AgentPanel";
import {VisionReviewButton} from "./VisionReview";
import {ImageGeneration} from "./ImageGeneration";
import { GraphWorkspace } from "./GraphWorkspace";
import { GraphDocuments } from "./GraphDocuments";
import { GraphAssetBinding } from "./GraphAssetBinding";
import { DocumentGeneration } from "./DocumentGeneration";
import { primaryRecord } from "./workflowLogic";
import { GroupResults } from "./Workflow";
import { RangeGeneration } from "./Workflow";
import { Select } from "./Select";
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

export function Original({ pid, refresh }: WorkspaceProps) {
  return <GraphDocuments pid={pid} onChanged={() => void refresh()} />;
}
export function Memory(props: WorkspaceProps) {
  return <GraphWorkspace {...props} />;
}

export function Documents({
  kind,
  ...props
}: WorkspaceProps & { kind: "skeleton" | "outline" }) {
  const [generating, setGenerating] = useState(false),[docGenerating,setDocGenerating]=useState(false),[docResults,setDocResults]=useState(false);
  const rows = props.records.filter((r) => r.kind === kind && primaryRecord(r)),
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
      {docGenerating && <DocumentGeneration pid={props.pid} kind={kind} target={record} records={props.records} refresh={props.refresh} onClose={()=>setDocGenerating(false)}/>}
      {docResults && <GroupResults pid={props.pid} kindFilter={kind} refresh={props.refresh} onClose={()=>setDocResults(false)}/>}
      {generating && <RangeGeneration initialOutlineId={record?.id} pid={props.pid} records={props.records} refresh={props.refresh} onClose={() => setGenerating(false)} />}
      <div className="section-tools document-tools">
        <div className="actions">
          {rows.length > 0 && (
            <Select
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
            </Select>
          )}
          {record && (
            <>
              <Badge source={record.source} />
              <span className="status-text">{reviewLabel(record.review)}</span>
            </>
          )}
        </div>
        <div className="actions">
          <button onClick={()=>setDocResults(true)}>查看文档候选</button>
          {kind === "outline" && <button onClick={() => setGenerating(true)}>按话范围生成脚本</button>}
          <button onClick={() => void create()}>
            <Plus size={16} />
            新建草稿
          </button>
          <button
            className="primary"
            onClick={() => setDocGenerating(true)}
          >
            <Sparkles size={16} />
            生成候选
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
          可以直接自由编辑，或调用文本模型生成候选，核对后采用。
        </Empty>
      )}
    </>
  );
}

function AssetDetails({
  record,
  onSaved,
  onClose,
  onConfirmed,
  canBindStyle,
  onRegenerate,
}: {
  record: RecordItem;
  onSaved: (r: RecordItem) => void;
  onClose: () => void;
  onConfirmed: () => void;
  canBindStyle: boolean;
  onRegenerate:(record:RecordItem)=>void;
}) {
  const draft = useDraft(record, onSaved),
    [review, setReview] = useState(false),
    [message, setMessage] = useState(""),
    [assetError, setAssetError] = useState(""),
    [recovering,setRecovering] = useState(false);
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
      onSaved(draft.head.current);
      onConfirmed();
    } catch (e) {
      setAssetError((e as Error).message);
    }
  };
  return (
    <Drawer title={record.kind === "style" && record.content.style_option ? `方案 ${record.content.style_option} · ${record.title}` : record.title} onClose={onClose}>
      <Badge source={record.source} />
      <ErrorNote message={assetError} />
      {message && <p className="notice">{message}</p>}
      <div className="actions">
        <button disabled={draft.dirty} onClick={()=>onRegenerate(draft.head.current)}>用模型重新生成候选</button>
        <VisionReviewButton target={draft.head.current} disabled={draft.dirty}/>
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
        {record.kind === "asset" && canBindStyle && <button disabled={draft.dirty} onClick={async () => {
          try {
            const next = await api<RecordItem>(base(record.project_id) + `/records/${record.id}/confirm-style`, json("POST", { version: draft.head.current.version }));
            draft.accept(next); draft.setContent(next.content); onSaved(next);
            setMessage("已关联当前画风并建立新版本，请重新审核资产。");
          } catch (e) { setAssetError((e as Error).message); }
        }}>确认符合当前画风</button>}
        {record.kind === "style" && (
          <button className="primary" disabled={draft.dirty} onClick={() => void choose()}>确认此画风</button>

        )}
      </div>
      {record.kind === "style" && draft.dirty && <p className="notice">请先保存属性，再确认此画风。</p>}
      {record.content.samples && <div className="style-samples">{record.content.samples.map((sample: any) => <figure key={sample.label}><img src={sample.url} alt={sample.label} /><figcaption>{sample.label}</figcaption></figure>)}</div>}
      {record.content.url && !record.content.samples && (
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
      {draft.error&&<div className="asset-draft-recovery"><p>当前编辑仍保留。可先比较“版本与审核”，再读取最新版本号继续保存；或明确放弃本地草稿。</p><div className="actions"><button disabled={recovering} onClick={async()=>{setRecovering(true);try{await draft.resolve();}finally{setRecovering(false);}}}>保留编辑并读取最新版本号</button><button disabled={recovering} onClick={async()=>{setRecovering(true);try{await draft.discard();}finally{setRecovering(false);}}}>放弃草稿并读取最新内容</button></div></div>}
      <div className="actions">
        <button className="primary" disabled={recovering} onClick={() => draft.retry()}>
          保存属性
        </button>
        <button onClick={() => setReview(true)}>版本与审核</button>
        <span className="muted">{draft.status}</span>
      </div>
      {record.kind === "asset" && <GraphAssetBinding record={draft.head.current} dirty={draft.dirty} onSaved={onSaved} />}
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
  onConfirmed,
  ...props
}: WorkspaceProps & { kind: "style" | "asset"; onConfirmed: () => void }) {
  const [filter, setFilter] = useState("全部"),
    [source, setSource] = useState("all"),
    [status, setStatus] = useState("all"),
    [selected, setSelected] = useState<RecordItem | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [generating,setGenerating]=useState<{target?:RecordItem}|null>(null),[styleAssistant,setStyleAssistant]=useState(false);
  const [styleState, setStyleState] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    api(base(props.pid) + "/style-selection").then(value => { if (alive) setStyleState(value); }).catch(e => { if (alive) { setStyleState(null); setError(e.message); } });
    return () => { alive = false; };
  }, [props.pid, props.records]);
  const styleReady = styleState?.status === "confirmed";
  const chosenStyle = props.records.find(r => r.id === styleState?.selection?.record_id);
  const chosenTitle = chosenStyle?.content.style_option ? `方案 ${chosenStyle.content.style_option} · ${styleState?.title}` : styleState?.title;
  const isChosenStyle = (r: RecordItem) => styleReady && r.id === styleState.selection.record_id && r.version === styleState.selection.version;
  const currentStyle = (r: RecordItem) => styleReady && r.content.style_reference?.record_id === styleState.selection.record_id && r.content.style_reference?.version === styleState.selection.version;
  const filtering = filter !== "全部" || source !== "all" || status !== "all";
  const rows = props.records.filter(
    (r) =>
      r.kind === kind && primaryRecord(r) &&
      (filter === "全部" || r.content.category === filter) &&
      (source === "all" || r.source === source) &&
      (status === "all" || (kind === "asset" && !currentStyle(r) ? status === "pending" : r.review === status)),
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
      {styleAssistant&&<Drawer title="同组三套画风方案" wide onClose={()=>setStyleAssistant(false)}><p className="notice">请AI先阅读原著与已采用审核的细纲，为同一主角、同一主场景提出三套二维画风测试。方案中逐套预览并明确生成，候选仍需核对采用。</p><AgentPanel pid={props.pid} stage="style" records={props.records} onChanged={props.refresh}/></Drawer>}
      {generating&&<ImageGeneration key={kind+":"+(generating.target?.id||"new")+":"+(generating.target?.version||0)} pid={props.pid} kind={kind} target={generating.target} records={props.records} refresh={props.refresh} onClose={()=>setGenerating(null)}/>}
      <div className="style-progress" role="status">
        <div><strong>{styleReady ? `已确认：${chosenTitle} · v${styleState.selection.version}` : styleState?.status === "stale" ? "画风版本已变化 · 请重新确认" : "先比较三版画风，再确认一版"}</strong>
        <p>{styleReady ? `${styleState.selection.source === "mock" ? "模拟画风，仅用于体验流程。" : ""}全面资产将绑定此画风版本；确认不会自动生成。` : "尚未确认当前画风，全面资产生成暂不可用。已有资产保留供查看。"}</p></div>
        {styleReady && kind === "style" && <button onClick={onConfirmed}>进入全面资产</button>}
      </div>
      <div className="section-tools">
        <div className="actions">
          <Select
            aria-label="资产分类"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            {["全部", "人物", "场景", "道具"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </Select>
          <Select
            aria-label="资产来源"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="all">全部来源</option>
            <option value="import">人工导入</option>
            <option value="mock">模拟</option>
            <option value="ai">AI生成/修改</option>
          </Select>
          <Select
            aria-label="审核状态"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">全部审核状态</option>
            <option value="pending">待审核</option>
            <option value="approved">已通过</option>
            <option value="changes">需修改</option>
          </Select>
        </div>
        <div className="actions">
          {kind==="style"&&<button className="primary" onClick={()=>setStyleAssistant(true)}>AI三套画风方案</button>}
          <button className="primary" disabled={busy||(kind==="asset"&&!styleReady)} onClick={()=>setGenerating({})}>模型生图（单图候选）</button>
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
            disabled={busy || (kind === "asset" && !styleReady)}
            onClick={async () => {
              setBusy(true);
              try {
                if (kind === "style") {
                  for (let i = 0; i < 3; i++) await props.run("style", undefined, { panel: i + 1 });
                } else await props.run("asset");
              } finally { setBusy(false); }
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
          ? "模拟三版使用同组预置人物与场景，并非当前小说效果。模型生图另按本次提示词和参考生成单图候选，采用后可展开并确认；AI三套方案基于当前原著与已审核细纲，可逐套预览或整组核对型号与三张提示词；明确授权后连续生成，候选仍须逐项采用审核。"
          : "人物、场景、道具按剧情状态整理。全书资产审核完成后，才满足正式制作的前期条件。"}
      </div>
      {rows.length ? (
        <div className={`asset-grid ${kind === "style" ? "style-comparison" : ""}`}>
          {rows.map((r) => (
            <button
              className={`asset-tile ${kind === "style" && isChosenStyle(r) ? "confirmed-style" : ""}`}
              key={r.id}
              onClick={() => setSelected(r)}
            >
              <div className="asset-image">
                {kind === "style" && r.content.samples ? <div className="style-samples">{r.content.samples.map((sample: any) => <figure key={sample.label}><img src={sample.url} alt={sample.label} loading="lazy" /><figcaption>{sample.label}</figcaption></figure>)}</div> : r.content.url ? (
                  <img src={r.content.url} alt={r.title} loading="lazy" />
                ) : (
                  <FileText />
                )}
                <span className="tile-source">
                  <Badge source={r.source} />
                </span>
              </div>
              <div className="asset-caption">
                {kind === "style" && isChosenStyle(r) && <span className="confirmed-style-label"><CheckCircle2 size={14} />当前已确认 · v{r.version}</span>}
                <strong>{kind === "style" && r.content.style_option ? `方案 ${r.content.style_option} · ${r.title}` : r.title}</strong>
                <span>
                  {r.content.category} · {r.content.state || "默认状态"}
                </span>
                {kind === "style" && <span>{r.content.samples ? "同组人物与场景 · 点击展开比较" : r.content.style_test_id ? "同组三套测试板 · 点击查看" : "画风参考 · 点击查看"}</span>}
                {kind === "asset" && <span className="style-reference">{currentStyle(r) ? `当前画风 · v${r.content.style_reference.version}` : r.content.style_reference ? `旧画风 · v${r.content.style_reference.version} · 待重新确认` : "未绑定画风 · 待重新确认"}</span>}
                <div>
                  <span className="status-text">{kind === "asset" && !currentStyle(r) ? "待重新确认" : reviewLabel(r.review)}</span>
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
            filtering
              ? "没有符合筛选条件的资产"
              : kind === "style"
                ? "为这部作品确定视觉语言"
                : "让每个角色与场景都有依据"
          }
          action={filtering && <button onClick={() => {
            setFilter("全部");
            setSource("all");
            setStatus("all");
          }}>清除筛选</button>}
        >
          {filtering
            ? "试试其他分类、来源或审核状态，也可以清除筛选查看全部资产。"
            : "导入 PNG/JPEG 参考图，记录状态与来源，并审核准确版本。"}
        </Empty>
      )}
      {selected && (
        <AssetDetails
          key={selected.id}
          record={selected}
          onRegenerate={record=>{setSelected(null);setGenerating({target:record});}}
          canBindStyle={styleReady && !currentStyle(selected)}
          onConfirmed={onConfirmed}
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
        <small>文本、单格图像、独立格批次与单图视觉复查可连接模型；前图依赖需采用审核后恢复；可选实图检查与一轮严重剧情返修；其他返修待接入。</small>
      </div>
    </div>
  );
}
