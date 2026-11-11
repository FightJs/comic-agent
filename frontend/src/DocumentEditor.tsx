import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Highlight from "@tiptap/extension-highlight";
import {
  Bold,
  List,
  Heading2,
  Undo2,
  Redo2,
  Sparkles,
  History,
  Save,
  Search,
} from "lucide-react";
import { api, base, json, recPath, type RecordItem } from "./api";
import { Badge, Drawer, ErrorNote, reviewLabel } from "./ui";
import { useDraft } from "./useDraft";
import { documentHtml,documentText,withDocumentHtml } from "./documentContent";
import {captureTextSelection,selectionHtml,type TextSelection} from "./textSelection";
import {SelectionAssistant} from "./SelectionAssistant";

export function RecordHistory({
  record,
  onClose,
  onSaved,
}: {
  record: RecordItem;
  onClose: () => void;
  onSaved: (r: RecordItem) => void;
}) {
  const [versions, setVersions] = useState<RecordItem[]>([]),
    [reviews, setReviews] = useState<any[]>([]),
    [selected, setSelected] = useState(record.version),
    [note, setNote] = useState(""),
    [error, setError] = useState("");
  const load = () =>
    Promise.all([
      api<RecordItem[]>(recPath(record) + "/versions"),
      api<any[]>(recPath(record) + "/reviews"),
    ])
      .then(([v, r]) => {
        setVersions(v);
        setReviews(r);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    void load();
  }, [record.id]);
  const review = async (decision: string) => {
    try {
      await api(
        recPath(record) + "/reviews",
        json("POST", { version: selected, decision, note }),
      );
      setNote("");
      await load();
      onSaved(await api(recPath(record)));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const version = versions.find((v) => v.version === selected);
  return (
    <Drawer title="版本与审核记录" onClose={onClose} wide>
      <ErrorNote message={error} />
      <div className="split">
        <div className="version-list">
          {versions.map((v) => (
            <button
              key={v.version}
              className={selected === v.version ? "selected" : ""}
              onClick={() => setSelected(v.version)}
            >
              <strong>版本 {v.version}</strong>
              <Badge source={v.source} />
              <small>{reviewLabel(v.review)}</small>
            </button>
          ))}
        </div>
        <div className="grow">
          <h3>
            {record.title} · v{selected}
          </h3>
          {version?.content.url ? (
            <img
              className="version-preview"
              src={version.content.url}
              alt={`${record.title} 版本 ${selected}`}
            />
          ) : (
            <pre className="text-preview">
              {version && ['skeleton','outline'].includes(version.kind) ? documentText(version.content) : JSON.stringify(version?.content,null,2)}
            </pre>
          )}
          <label>
            审核意见
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="记录本版本的结论或需要修改的内容"
            />
          </label>
          <div className="actions">
            <button className="primary" onClick={() => void review("approved")}>
              {version?.source === "mock" ? "模拟审核通过" : "通过此版本"}
            </button>
            <button onClick={() => void review("changes")}>需要修改</button>
          </div>
          <p className="muted">
            审核绑定 v{selected}。修改内容会生成新草稿，原审核记录保留。
          </p>
          <div className="timeline">
            {reviews.map((r) => (
              <div key={r.id}>
                <strong>
                  v{r.version} · {reviewLabel(r.decision)}
                </strong>{" "}
                <Badge source={r.source} />
                <p>{r.note || "未填写意见"}</p>
                <small>{new Date(r.created).toLocaleString("zh-CN")}</small>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Drawer>
  );
}

export function DocumentEditor({
  record,
  onSaved,
}: {
  record: RecordItem;
  onSaved: (r: RecordItem) => void;
}) {
  const draft = useDraft(record, onSaved),
    [history, setHistory] = useState(false),
    [chat, setChat] = useState(false),
    [selected, setSelected] = useState<TextSelection|null>(null),
    [selectionError,setSelectionError]=useState(''),
    [search, setSearch] = useState("");
  const alive = useRef(true);
  const selectionBase=useRef({html:'',version:record.version});
  useEffect(
    () => {alive.current=true;return () => {alive.current = false;};},
    [],
  );
  const editor = useEditor({
    extensions: [StarterKit, Highlight.configure({ multicolor: false })],
    content: documentHtml(draft.content),
    editorProps: {
      attributes: {
        class: "document-prose",
        "aria-label": "文档正文",
        role: "textbox",
        "aria-multiline": "true",
      },
    },
    onUpdate: ({ editor }) =>
      draft.setContent((c) => withDocumentHtml(c,editor.getHTML())),
  });
  useEffect(() => {
    if (
      editor &&
      !draft.dirty &&
      editor.getHTML() !== documentHtml(draft.content)
    )
      editor.commands.setContent(documentHtml(draft.content), {
        emitUpdate: false,
      });
  }, [draft.content, editor]);
  const searchText = () => {
    if (!editor || !search) return;
    let found = false;
    editor.state.doc.descendants((node, pos) => {
      if (found || !node.isText) return;
      const at = node.text?.indexOf(search) ?? -1;
      if (at >= 0) {
        editor
          .chain()
          .setTextSelection({ from: pos + at, to: pos + at + search.length })
          .scrollIntoView()
          .run();
        found = true;
      }
    });
  };
  return (
    <div className="editor-wrap">
      <div className="editor-toolbar">
        <div className="actions compact">
          <button
            title="加粗"
            aria-label="加粗"
            onClick={() => editor?.chain().focus().toggleBold().run()}
          >
            <Bold size={16} />
          </button>
          <button
            title="二级标题"
            aria-label="二级标题"
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            <Heading2 size={18} />
          </button>
          <button
            title="列表"
            aria-label="列表"
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
          >
            <List size={17} />
          </button>
          <span className="divider" />
          <button
            aria-label="撤销"
            onClick={() => editor?.chain().focus().undo().run()}
          >
            <Undo2 size={16} />
          </button>
          <button
            aria-label="重做"
            onClick={() => editor?.chain().focus().redo().run()}
          >
            <Redo2 size={16} />
          </button>
        </div>
        <div className="actions compact">
          <span
            className={`save-state ${draft.error ? "danger" : ""}`}
            aria-live="polite"
          >
            {draft.status}
          </span>
          <button onClick={() => void draft.retry()}>
            <Save size={15} />
            保存
          </button>
          <button onClick={() => setHistory(true)}>
            <History size={15} />
            版本与审核
          </button>
        </div>
      </div>
      <ErrorNote message={draft.error} />
      {draft.error && (
        <button onClick={() => void draft.resolve()}>
          保留当前编辑并读取最新版本号
        </button>
      )}
      <div className="editor-tools">
        <div className="search small">
          <Search size={15} />
          <input
            aria-label="搜索文档"
            placeholder="查找正文"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") searchText();
            }}
          />
          <button onClick={searchText}>定位</button>
        </div>
        <button
          onClick={() => {
            if (!editor) return;
            if(draft.dirty||draft.error){setSelectionError('请先保存或处理文档草稿，再选择正文使用 AI。');return;}
            const captured=captureTextSelection(editor);
            if(captured&&captured.text.length>20000){setSelectionError('选段超过20000字符，请缩小范围。');return;}
            setSelectionError('');setSelected(captured);
            selectionBase.current={html:editor.getHTML(),version:draft.head.current.version};
            setChat(true);
          }}
        >
          <Sparkles size={15} />
          选段 AI 修改
        </button>
      </div>
      <ErrorNote message={selectionError}/>
      <div className="document-layout">
        <aside className="document-outline">
          <span className="muted">文档目录</span>
          {Array.from(
            new DOMParser()
              .parseFromString(documentHtml(draft.content), "text/html")
              .querySelectorAll("h1,h2,h3"),
          ).map((h, i) => (
            <button
              key={i}
              onClick={() => {
                document
                  .querySelectorAll(".tiptap h1,.tiptap h2,.tiptap h3")
                  [i]?.scrollIntoView({ block: "center" });
              }}
            >
              {h.textContent}
            </button>
          ))}
        </aside>
        <EditorContent editor={editor} />
      </div>
      {chat && <SelectionAssistant record={draft.head.current} selection={selected} onClose={()=>setChat(false)} onApply={async proposal=>{
        if(!editor||draft.dirty||draft.error||editor.getHTML()!==selectionBase.current.html||draft.head.current.version!==proposal.changes[0].version)throw Error('正文、版本或未保存草稿已变化，未采用；请重新选择正文讨论。');
        const html=selectionHtml(editor,proposal.changes[0].selection,proposal.changes[0].patch.text);
        editor.setEditable(false);
        try{
          const saved=await api<RecordItem>(base(record.project_id)+'/agent/proposals/'+proposal.id+'/apply-selection',json('POST',{expected_version:proposal.changes[0].version,html}));
          if(!alive.current)return;
          draft.accept(saved);draft.setContent(saved.content);
          editor.commands.setContent(documentHtml(saved.content),{emitUpdate:false});
          selectionBase.current={html:editor.getHTML(),version:saved.version};
          onSaved(saved);
        }finally{if(alive.current)editor.setEditable(true);}
      }}/>}
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
