export type OutlineEntry = {
  episode: number;
  title: string;
  text: string;
  source_range: string;
};
export const scriptFields = [
  ["panel", "格号"],
  ["characters", "出现角色"],
  ["scene", "当前场景"],
  ["weather", "当前天气"],
  ["time", "当前时间"],
  ["shot", "景别"],
  ["camera", "机位角度"],
  ["description", "画面内容"],
  ["dialogue", "台词"],
  ["sfx", "特效字"],
  ["note", "画面备注"],
];
export const promptFields = [
  ["scene_prompt", "场景提示词"],
  ["content_prompt", "内容提示词"],
  ["position_prompt", "站位提示词"],
  ["shot_prompt", "分镜"],
  ["constraints", "其他约束"],
];
export function composePrompt(c: Record<string, any>) {
  return promptFields
    .filter(([k]) => c[k]?.trim())
    .map(([k, label]) => `${label}：${c[k]}`)
    .join("\n\n");
}
export function wheelTransform(scale: number, delta: number) {
  return Math.min(
    6,
    Math.max(
      0.05,
      scale * Math.exp(-Math.max(-100, Math.min(100, delta)) * 0.002),
    ),
  );
}
function number(value: string) {
  if (/^\d+$/.test(value)) return Number(value);
  const digits = "零一二三四五六七八九";
  let total = 0,
    n = 0;
  for (const c of value) {
    const d = digits.indexOf(c);
    if (d >= 0) n = d;
    else if (c === "两") n = 2;
    else {
      const unit = ({ 十: 10, 百: 100, 千: 1000 } as Record<string, number>)[c];
      if (unit) {
        total += (n || 1) * unit;
        n = 0;
      }
    }
  }
  return total + n;
}
export function parseOutline(html: string): OutlineEntry[] {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const text = doc.body.innerHTML
    .replace(/<\/(?:p|h[1-6]|div)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n");
  const clean =
    new DOMParser().parseFromString(text, "text/html").body.textContent || "";
  const matches = [
    ...clean.matchAll(
      /(?:^|\n)\s*第([零一二三四五六七八九十百千两\d]+)话([^\n]*)/g,
    ),
  ];
  return matches.map((m, i) => ({
    episode: number(m[1]),
    title: (m[2].replace(/^[\s·:：—-]+/, "") || `第${m[1]}话`).trim(),
    text: clean
      .slice(m.index! + m[0].length, matches[i + 1]?.index ?? clean.length)
      .trim(),
    source_range: "",
  }));
}
export const primaryRecord = (r: any) =>
  !r.content.candidate_for && !r.content.creation_candidate && !r.content.pending_for && !r.content.rejected && !r.content.adopted_into && !r.content.deleted_by_script && r.adopted !== 0;
export function clearSubmittedMessage(current: string, submitted: string) {
  return current === submitted ? "" : current;
}
export function cancelAnnotationEdit<T extends { id: string }>(
  items: T[],
  id: string,
  original: T | null,
): T[] {
  return original
    ? items.map((a) => (a.id === id ? original : a))
    : items.filter((a) => a.id !== id);
}
