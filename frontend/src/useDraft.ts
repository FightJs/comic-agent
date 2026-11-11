import { useEffect, useRef, useState } from "react";
import { api, json, recPath, type RecordItem } from "./api";
export function useDraft(record: RecordItem, onSaved: (r: RecordItem) => void) {
  const key = `comic-draft:${record.project_id}:${record.id}`;
  const cached = useRef(
    (() => {
      try {
        return JSON.parse(localStorage.getItem(key) || "null");
      } catch {
        return null;
      }
    })(),
  );
  const [content, setContent] = useState<Record<string, any>>(
      cached.current?.content || record.content,
    ),
    [status, setStatus] = useState(
      cached.current ? "恢复的未保存草稿" : "已保存",
    ),
    [error, setError] = useState(
      cached.current && cached.current.version !== record.version
        ? "恢复草稿与服务器版本不同。请比较版本后保存。"
        : "",
    );
  const head = useRef(record),
    latest = useRef(content),
    saved = useRef(JSON.stringify(record.content)),
    busy = useRef(false),
    blocked = useRef(!!error),
    alive = useRef(true),
    mockPending = useRef(cached.current?.mockPending || false);
  latest.current = content;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (
      record.version !== head.current.version &&
      !busy.current &&
      JSON.stringify(latest.current) === saved.current
    ) {
      head.current = record;
      saved.current = JSON.stringify(record.content);
      setContent(record.content);
      setStatus("已保存");
    }
  }, [record.version]);
  const dirty = JSON.stringify(content) !== saved.current;
  const accept = (result: RecordItem) => {
    head.current = result;
    saved.current = JSON.stringify(result.content);
    if (JSON.stringify(latest.current) === saved.current) {
      localStorage.removeItem(key);
    }
    if (alive.current) setStatus("已保存");
  };
  const save = async () => {
    if (
      busy.current ||
      blocked.current ||
      JSON.stringify(latest.current) === saved.current
    )
      return;
    busy.current = true;
    setStatus("保存中");
    setError("");
    const snapshot = latest.current;
    const usedMock = mockPending.current;
    try {
      const result = await api<RecordItem>(
        recPath(head.current) + (usedMock ? "/mock-edit" : ""),
        json(usedMock ? "POST" : "PUT", {
          expected_version: head.current.version,
          content: snapshot,
        }),
      );
      if (usedMock) mockPending.current = false;
      accept(result);
      onSaved(result);
      if (alive.current)
        setStatus(
          JSON.stringify(latest.current) === saved.current
            ? "已保存"
            : "未保存",
        );
    } catch (e) {
      blocked.current = true;
      if (alive.current) {
        setError((e as Error).message);
        setStatus("保存失败");
      }
    } finally {
      busy.current = false;
      if (!blocked.current && JSON.stringify(latest.current) !== saved.current)
        setTimeout(() => void save(), 30);
    }
  };
  useEffect(() => {
    if (!dirty) return;
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          version: head.current.version,
          content,
          mockPending: mockPending.current,
        }),
      );
    } catch {
      setError("浏览器草稿缓存不可用，请保存后再切换页面。");
    }
    setStatus("未保存");
    const t = setTimeout(() => void save(), 900);
    return () => clearTimeout(t);
  }, [content]);
  useEffect(() => {
    const fn = (e: BeforeUnloadEvent) => {
      if (JSON.stringify(latest.current) !== saved.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", fn);
    return () => window.removeEventListener("beforeunload", fn);
  }, []);
  return {
    content,
    setContent,
    status,
    error,
    dirty,
    version: head.current.version,
    save,
    retry: () => {
      blocked.current = false;
      void save();
    },
    resolve: async () => {
      try {
        const current = await api<RecordItem>(recPath(head.current));
        head.current = current;
        blocked.current = false;
        setError("已读取最新版本号；当前编辑仍保留，点击保存将建立新版本。");
      } catch {
        blocked.current = true;
        setError("无法读取最新版本。当前编辑已保留，请恢复连接后重试。");
        setStatus("读取失败");
      }
    },
    discard: async () => {
      if (busy.current) return;
      busy.current = true;
      const snapshot = JSON.stringify(latest.current);
      setStatus("读取中");
      try {
        const current = await api<RecordItem>(recPath(head.current));
        if (!alive.current) return;
        if (JSON.stringify(latest.current) !== snapshot) {
          blocked.current = true;
          setError("读取期间编辑已变化，草稿仍保留；请重新核对后再放弃。");
          setStatus("编辑已保留");
          return;
        }
        head.current = current;
        latest.current = current.content;
        saved.current = JSON.stringify(current.content);
        blocked.current = false;
        mockPending.current = false;
        localStorage.removeItem(key);
        setContent(current.content);
        setError("");
        setStatus("已保存");
        onSaved(current);
      } catch {
        blocked.current = true;
        if (alive.current) {
          setError("无法读取最新内容，草稿仍保留；恢复连接后可重试。");
          setStatus("读取失败");
        }
      } finally {
        busy.current = false;
      }
    },
    head,
    accept,
    flagError: (message: string) => {
      blocked.current = true;
      mockPending.current = true;
      setError(message);
      setStatus("保存失败");
    },
    markMock: () => {
      mockPending.current = true;
    },
  };
}
