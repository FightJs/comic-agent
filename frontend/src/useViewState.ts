import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
export function useViewState<T>(
  key: string,
  fallback: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (
        JSON.parse(localStorage.getItem("comic-ui:" + key) || "null") ??
        fallback
      );
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("comic-ui:" + key, JSON.stringify(value));
    } catch {}
  }, [key, value]);
  return [value, setValue];
}
