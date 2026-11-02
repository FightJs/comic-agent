export type RecordItem = {
  id: string;
  project_id: string;
  kind: string;
  title: string;
  version: number;
  adopted: number;
  source: string;
  review: string;
  created: string;
  updated: string;
  content: Record<string, any>;
};
export type Project = {
  id: string;
  name: string;
  archived: boolean;
  updated: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "服务不可用" }));
    throw new ApiError(
      response.status,
      typeof data.detail === "string"
        ? data.detail
        : "输入格式无效，请检查内容",
    );
  }
  return response.json();
}
export const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
export const base = (p: string) => `/projects/${p}`;
export const recPath = (r: RecordItem) =>
  `${base(r.project_id)}/records/${r.id}`;
export function downloadUrl(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}
export async function downloadZip(pid: string, ids: string[]) {
  const res = await fetch(
    `/api/projects/${pid}/download`,
    json("POST", { ids }),
  );
  if (!res.ok) throw new Error("下载失败，请确认图片仍存在");
  const url = URL.createObjectURL(await res.blob());
  downloadUrl(url, "选中图片.zip");
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
