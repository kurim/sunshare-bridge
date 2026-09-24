import { useEffect, useRef, useState } from "react";
import { getHistoryLong, type HistoryLong, type HistorySpec } from "./api";

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

/** Averaged samples from the bridge's database for `spec` (null = not needed), refreshed every
 * minute. `spec` is keyed by a primitive string so a fresh object literal each render doesn't
 * re-trigger the effect. */
export function useLongHistory(spec: HistorySpec | null): HistoryLong | null {
  const [data, setData] = useState<HistoryLong | null>(null);
  const key = spec ? ("minutes" in spec ? `m:${spec.minutes}` : `r:${spec.range}`) : null;
  useEffect(() => {
    setData(null);
    if (!spec) return;
    let cancelled = false;
    const load = () => getHistoryLong(spec).then((d) => { if (!cancelled) setData(d); }).catch(() => undefined);
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 60_000);
    return () => { cancelled = true; clearInterval(id); };
    // `key` fully determines `spec`'s content - depending on it (not `spec` itself) avoids
    // re-fetching every render just because the caller passed a new object with the same value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return data;
}
