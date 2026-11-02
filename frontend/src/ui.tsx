import { useEffect, useRef, type ReactNode } from "react";
import { AlertCircle, FolderOpen, X, LoaderCircle } from "lucide-react";
import { sourceLabel } from "./logic";
export function Badge({ source }: { source: string }) {
  return (
    <span className={`badge ${source === "mock" ? "mock" : ""}`}>
      {sourceLabel(source)}
    </span>
  );
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <FolderOpen size={34} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function ErrorNote({ message }: { message: string }) {
  return message ? (
    <div className="notice error" role="alert">
      <AlertCircle size={16} />
      <span>{message}</span>
    </div>
  ) : null;
}
export function Busy() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={18} /> 正在读取本地数据…
    </div>
  );
}
export function Drawer({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement;
    const el = dialog.current;
    el?.showModal();
    return () => {
      el?.close();
      requestAnimationFrame(() => trigger?.isConnected && trigger.focus());
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="drawer-backdrop"
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section className={`drawer ${wide ? "wide" : ""}`}>
        <header>
          <h2>{title}</h2>
          <button onClick={onClose} aria-label="关闭面板">
            <X size={19} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </section>
    </dialog>
  );
}

export const reviewLabel = (status: string) =>
  ({ approved: "已通过", changes: "需修改", pending: "待审核" })[status] ||
  status;
