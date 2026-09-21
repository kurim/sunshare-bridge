import { useEffect, useRef, useState } from "react";
import { getHistoryLong, type HistoryLong } from "./api";

/** Current time as epoch seconds, ticking every `ms`. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) setNow(Date.now() / 1000); }, ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/** Element width, following resizes. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** Averaged samples from the bridge's database for `minutes` (0 = not needed), refreshed every minute. */
export function useLongHistory(minutes: number): HistoryLong | null {
  const [data, setData] = useState<HistoryLong | null>(null);
  useEffect(() => {
    setData(null);
    if (!minutes) return;
    let cancelled = false;
    const load = () => getHistoryLong(minutes).then((d) => { if (!cancelled) setData(d); }).catch(() => undefined);
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [minutes]);
  return data;
}
