import { useEffect, useRef, useState } from "react";
import {
  Stage,
  Layer,
  Image as KonvaImage,
  Rect,
  Circle,
  Line,
  Text,
} from "react-konva";
import {
  MousePointer2,
  Square,
  Paintbrush,
  Shield,
  Hand,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Trash2,
  Save,
  Maximize,
} from "lucide-react";
import { api, json, recPath, type RecordItem } from "./api";
import { ErrorNote } from "./ui";
import { toImagePoint } from "./logic";
export type Annotation = {
  id: string;
  type: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  points?: number[];
  brushWidth?: number;
  note?: string;
};
export function AnnotationCanvas({ record }: { record: RecordItem }) {
  const [image, setImage] = useState<HTMLImageElement | null>(null),
    [tool, setTool] = useState("point"),
    [items, setItems] = useState<Annotation[]>([]),
    [selected, setSelected] = useState(""),
    [scale, setScale] = useState(0.6),
    [offset, setOffset] = useState({ x: 30, y: 30 }),
    [size, setSize] = useState({ width: 700, height: 640 }),
    [error, setError] = useState(""),
    [status, setStatus] = useState("正在读取标注"),
    [ready, setReady] = useState(false);
  const container = useRef<HTMLDivElement>(null),
    stage = useRef<any>(null),
    version = useRef(0),
    undo = useRef<Annotation[][]>([]),
    redo = useRef<Annotation[][]>([]),
    drawing = useRef<Annotation | null>(null),
    start = useRef({ x: 0, y: 0 }),
    latest = useRef(items),
    saved = useRef("[]"),
    busy = useRef(false),
    blocked = useRef(false);
  latest.current = items;
  const key = `comic-annotations:${record.id}:${record.version}`;
  const fit = () => {
    const s = Math.min(
      (size.width - 60) / record.content.width,
      (size.height - 60) / record.content.height,
      1,
    );
    setScale(s);
    setOffset({
      x: (size.width - record.content.width * s) / 2,
      y: (size.height - record.content.height * s) / 2,
    });
  };
  useEffect(() => {
    if (!container.current) return;
    const obs = new ResizeObserver(([e]) =>
      setSize({
        width: e.contentRect.width,
        height: Math.max(500, Math.min(750, window.innerHeight - 290)),
      }),
    );
    obs.observe(container.current);
    return () => obs.disconnect();
  }, []);
  useEffect(() => {
    fit();
  }, [size.width, size.height, record.id]);
  useEffect(() => {
    const im = new Image();
    im.onload = () => setImage(im);
    im.onerror = () => setError("底图读取失败");
    im.src = record.content.url;
    let alive = true;
    api(recPath(record) + `/annotations?image_version=${record.version}`)
      .then((value) => {
        if (!alive) return;
        version.current = value.version;
        saved.current = JSON.stringify(value.items);
        let cache;
        try {
          cache = JSON.parse(localStorage.getItem(key) || "null");
        } catch {}
        setItems(cache?.items || value.items);
        if (cache && cache.version !== value.version) {
          blocked.current = true;
          setError("本地未保存标注与服务器版本冲突，请比较后重新保存。");
        }
        setReady(true);
        setStatus(cache ? "恢复的未保存标注" : "已保存");
      })
      .catch((e) => setError(e.message));
    return () => {
      alive = false;
    };
  }, [key]);
  const commit = (next: Annotation[]) => {
    undo.current.push(latest.current);
    redo.current = [];
    setItems(next);
    setStatus("未保存");
  };
  const save = async () => {
    if (
      !ready ||
      busy.current ||
      blocked.current ||
      saved.current === JSON.stringify(latest.current)
    )
      return;
    busy.current = true;
    setStatus("保存中");
    const snapshot = latest.current;
    try {
      const r = await api(
        recPath(record) + "/annotations",
        json("PUT", {
          expected_version: version.current,
          image_version: record.version,
          items: snapshot,
        }),
      );
      version.current = r.version;
      saved.current = JSON.stringify(snapshot);
      if (JSON.stringify(latest.current) === saved.current)
        localStorage.removeItem(key);
      setStatus("已保存");
      setError("");
    } catch (e) {
      blocked.current = true;
      setError((e as Error).message);
      setStatus("保存失败");
    } finally {
      busy.current = false;
      if (!blocked.current && JSON.stringify(latest.current) !== saved.current)
        setTimeout(() => void save(), 30);
    }
  };
  useEffect(() => {
    if (!ready || JSON.stringify(items) === saved.current) return;
    localStorage.setItem(
      key,
      JSON.stringify({ version: version.current, items }),
    );
    const t = setTimeout(() => void save(), 700);
    return () => clearTimeout(t);
  }, [items, ready]);
  const point = () => {
    const p = stage.current?.getPointerPosition();
    if (!p) return null;
    const q = toImagePoint(p, offset, scale);
    return {
      x: Math.max(0, Math.min(record.content.width, q.x)),
      y: Math.max(0, Math.min(record.content.height, q.y)),
    };
  };
  const down = (e: any) => {
    if (!ready || tool === "pan" || tool === "select") return;
    const p = point();
    if (!p) return;
    start.current = p;
    const a: Annotation = {
      id: crypto.randomUUID(),
      type: tool,
      x: p.x,
      y: p.y,
      width: 0,
      height: 0,
      note: "",
    };
    if (tool === "brush") {
      a.brushWidth = Math.min(
        16 / scale,
        Math.max(record.content.width, record.content.height),
      );
      a.points = [p.x, p.y];
      delete a.x;
      delete a.y;
      delete a.width;
      delete a.height;
    }
    drawing.current = a;
    setSelected(a.id);
    undo.current.push(latest.current);
    redo.current = [];
    setItems([...latest.current, a]);
    e.evt.preventDefault();
  };
  const move = () => {
    if (!drawing.current) return;
    const p = point();
    if (!p) return;
    const a = drawing.current;
    if (a.type === "brush") a.points = [...(a.points || []), p.x, p.y];
    else if (a.type !== "point") {
      a.x = Math.min(start.current.x, p.x);
      a.y = Math.min(start.current.y, p.y);
      a.width = Math.abs(p.x - start.current.x);
      a.height = Math.abs(p.y - start.current.y);
    }
    setItems(latest.current.map((x) => (x.id === a.id ? { ...a } : x)));
  };
  const up = () => {
    drawing.current = null;
  };
  const chosen = items.find((a) => a.id === selected);
  return (
    <div className="annotation-shell">
      <div className="canvas-toolbar">
        {[
          ["select", "选择", MousePointer2],
          ["point", "点选", MousePointer2],
          ["rect", "框选", Square],
          ["brush", "画笔", Paintbrush],
          ["protect", "保护区", Shield],
          ["pan", "平移", Hand],
        ].map(([id, label, Icon]: any) => (
          <button
            key={id}
            title={label}
            aria-label={label}
            className={tool === id ? "selected" : ""}
            onClick={() => setTool(id)}
          >
            <Icon size={17} />
            <span>{label}</span>
          </button>
        ))}
        <span className="divider" />
        <button
          aria-label="撤销标注"
          disabled={!undo.current.length}
          onClick={() => {
            redo.current.push(items);
            setItems(undo.current.pop()!);
          }}
        >
          <Undo2 size={17} />
        </button>
        <button
          aria-label="重做标注"
          disabled={!redo.current.length}
          onClick={() => {
            undo.current.push(items);
            setItems(redo.current.pop()!);
          }}
        >
          <Redo2 size={17} />
        </button>
        <button
          aria-label="缩小"
          onClick={() => setScale((s) => Math.max(0.05, s / 1.2))}
        >
          <ZoomOut size={17} />
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button
          aria-label="放大"
          onClick={() => setScale((s) => Math.min(6, s * 1.2))}
        >
          <ZoomIn size={17} />
        </button>
        <button aria-label="适应画布" onClick={fit}>
          <Maximize size={17} />
        </button>
      </div>
      <ErrorNote message={error} />
      {error && (
        <button
          onClick={async () => {
            try {
              const r = await api(
                recPath(record) +
                  `/annotations?image_version=${record.version}`,
              );
              version.current = r.version;
              blocked.current = false;
              setReady(true);
              setError("已读取服务器版本号，本地标注保留。请保存。");
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          保留本地标注并读取最新版本号
        </button>
      )}
      <div className="canvas-area" ref={container}>
        <Stage
          ref={stage}
          width={size.width}
          height={size.height}
          scaleX={scale}
          scaleY={scale}
          x={offset.x}
          y={offset.y}
          draggable={tool === "pan"}
          onDragEnd={(e) => {
            if (e.target === stage.current)
              setOffset({ x: e.target.x(), y: e.target.y() });
          }}
          onMouseDown={down}
          onMouseMove={move}
          onMouseUp={up}
          onMouseLeave={up}
          onWheel={(e) => {
            e.evt.preventDefault();
            const p = stage.current.getPointerPosition(),
              before = toImagePoint(p, offset, scale),
              next = Math.min(
                6,
                Math.max(0.05, scale * (e.evt.deltaY > 0 ? 0.9 : 1.1)),
              );
            setScale(next);
            setOffset({ x: p.x - before.x * next, y: p.y - before.y * next });
          }}
        >
          <Layer>
            {image && (
              <KonvaImage
                image={image}
                width={record.content.width}
                height={record.content.height}
              />
            )}
            {items.map((a, i) => {
              const color =
                a.type === "protect"
                  ? "#67d7be"
                  : a.id === selected
                    ? "#ffe083"
                    : "#ff916c";
              const common = {
                stroke: color,
                strokeWidth: 2 / scale,
                onClick: () => {
                  if (tool === "select") setSelected(a.id);
                },
                hitStrokeWidth: 12 / scale,
              };
              return (
                <RectGroup
                  key={a.id}
                  a={a}
                  index={i}
                  common={common}
                  scale={scale}
                  color={color}
                />
              );
            })}
          </Layer>
        </Stage>
        <span className="canvas-caption">
          原图 {record.content.width} × {record.content.height} · v
          {record.version} · 标注单独保存
        </span>
      </div>
      <div className="annotation-bottom">
        <div>
          <strong>问题与保护区域</strong>
          <span className="muted">
            {" "}
            {items.length} 处 · {status}
          </span>
        </div>
        <button
          onClick={() => {
            blocked.current = false;
            void save();
          }}
        >
          <Save size={15} />
          保存标注
        </button>
      </div>
      <div className="annotation-notes">
        <div className="annotation-list">
          {items.map((a, i) => (
            <button
              key={a.id}
              className={selected === a.id ? "selected" : ""}
              onClick={() => setSelected(a.id)}
            >
              {i + 1}. {a.type === "protect" ? "保护区" : "修改区域"} ·{" "}
              {a.note || "待填写说明"}
            </button>
          ))}
          {!items.length && (
            <p className="muted">用点、框或画笔标记，再说明要改成什么。</p>
          )}
        </div>
        {chosen && (
          <div className="annotation-detail">
            <label>
              {chosen.type === "protect" ? "需要保留的内容" : "修改目标"}
              <textarea
                value={chosen.note || ""}
                onChange={(e) =>
                  commit(
                    items.map((a) =>
                      a.id === chosen.id ? { ...a, note: e.target.value } : a,
                    ),
                  )
                }
                placeholder="说明正确目标、需移除内容或连接关系"
              />
            </label>
            <button
              className="danger"
              onClick={() => commit(items.filter((a) => a.id !== chosen.id))}
            >
              <Trash2 size={14} />
              删除此标注
            </button>
          </div>
        )}
      </div>
      <p className="muted padded">
        保护区用于表达保留意图；未接入模型，不承诺区域外像素锁定。更换底图会使用独立标注。
      </p>
    </div>
  );
}
function RectGroup({
  a,
  index,
  common,
  scale,
  color,
}: {
  a: Annotation;
  index: number;
  common: any;
  scale: number;
  color: string;
}) {
  return (
    <>
      {a.type === "point" ? (
        <Circle {...common} x={a.x} y={a.y} radius={8 / scale} />
      ) : a.type === "brush" ? (
        <Line
          {...common}
          points={a.points}
          lineCap="round"
          lineJoin="round"
          strokeWidth={a.brushWidth ?? 16}
          opacity={0.55}
        />
      ) : (
        <Rect
          {...common}
          x={a.x}
          y={a.y}
          width={a.width}
          height={a.height}
          fill={a.type === "protect" ? "#67d7be22" : "#ff916c18"}
          dash={a.type === "protect" ? [8 / scale, 5 / scale] : undefined}
        />
      )}
      <Text
        x={a.x ?? a.points?.[0]}
        y={(a.y ?? a.points?.[1] ?? 0) - 20 / scale}
        text={String(index + 1)}
        fill={color}
        fontSize={16 / scale}
      />
    </>
  );
}
