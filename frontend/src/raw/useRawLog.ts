import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getMe, getRaw, type RawEntry, type RawEvent } from "../api";
import { API_BASE } from "../basePath";

export type ParsedEntry = RawEntry & { obj: Record<string, unknown> | null };

export interface FieldInfo {
  key: string;
  value: string;
  changes: number;
  count: number;
}

function parse(entry: RawEntry): ParsedEntry {
  let obj: Record<string, unknown> | null = null;
  try {
    const o: unknown = JSON.parse(entry.body);
    if (o && typeof o === "object" && !Array.isArray(o)) obj = o as Record<string, unknown>;
  } catch { /* not JSON: shown as text */ }
  return { ...entry, obj };
}

/**
 * The bridge's raw push log. The buffer (ring of `size` entries) is fetched once per connection and
 * the live events that follow are applied on top; events that arrive while the snapshot loads are
 * replayed afterwards (entries the snapshot already contains are skipped). The data lives in a ref and
 * the view re-renders at most once per frame, because pushes arrive every few seconds but may burst.
 */
export function useRawLog(onSessionEnded: () => void) {
  const store = useRef({
    entries: [] as ParsedEntry[],
    byId: new Map<number, ParsedEntry>(),
    fields: new Map<string, FieldInfo>(),
    size: 500,
  });
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const [up, setUp] = useState(false);
  const [paused, setPausedState] = useState(false);
  const pausedRef = useRef(false);
  const pending = useRef<RawEvent[]>([]);
  const frame = useRef(0);

  const schedule = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => { frame.current = 0; rerender(); });
  }, []);

  const ingest = useCallback((raw: RawEntry) => {
    const s = store.current;
    const entry = parse(raw);
    s.entries.push(entry);
    s.byId.set(entry.id, entry);
    if (s.entries.length > s.size) s.byId.delete(s.entries.shift()!.id);
    if (!entry.obj) return;
    for (const [key, v] of Object.entries(entry.obj)) {
      const value = typeof v === "string" ? v : JSON.stringify(v);
      const f = s.fields.get(key);
      if (!f) s.fields.set(key, { key, value, changes: 0, count: 1 });
      else { if (f.value !== value) { f.value = value; f.changes++; } f.count++; }
    }
  }, []);

  const reset = useCallback(() => {
    const s = store.current;
    s.entries = []; s.byId = new Map(); s.fields = new Map();
  }, []);

  const apply = useCallback((event: RawEvent) => {
    const s = store.current;
    if (event.type === "add") ingest(event.entry);
    else if (event.type === "resp") {
      const e = s.byId.get(event.id);
      if (e) { e.resp_status = event.resp_status; e.resp_body = event.resp_body; }
    } else if (event.type === "clear") reset();
    schedule();
  }, [ingest, reset, schedule]);

  useEffect(() => {
    let source: EventSource | null = null;
    let syncing = false;
    let buffered: RawEvent[] = [];

    const resync = async (size: number) => {
      syncing = true;
      buffered = [];
      store.current.size = size;
      let snapshot: RawEntry[] = [];
      try { snapshot = await getRaw(); } catch { /* the stream will bring the next hello */ }
      reset();
      snapshot.forEach(ingest);
      const lastId = snapshot.length ? snapshot[snapshot.length - 1].id : 0;
      syncing = false;
      for (const ev of buffered) if (ev.type !== "add" || ev.entry.id > lastId) apply(ev);
      buffered = [];
      schedule();
    };

    const handle = (event: RawEvent) => {
      if (event.type === "hello") void resync(event.size);
      else if (syncing) buffered.push(event);
      else apply(event);
    };

    const open = () => {
      if (source || document.hidden) return;
      source = new EventSource(`${API_BASE}/raw/stream`);
      source.onopen = () => setUp(true);
      source.onerror = () => {
        setUp(false);
        getMe().then((me) => { if (!me.authenticated) onSessionEnded(); }).catch(() => undefined);
      };
      source.onmessage = (ev) => {
        const event = JSON.parse(ev.data) as RawEvent;
        if (pausedRef.current && event.type !== "hello") pending.current.push(event);
        else handle(event);
      };
    };
    const close = () => { source?.close(); source = null; setUp(false); };
    const onVisibility = () => (document.hidden ? close() : open());

    open();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", close);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", close);
      close();
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [apply, ingest, reset, schedule, onSessionEnded]);

  const setPaused = useCallback((value: boolean) => {
    pausedRef.current = value;
    setPausedState(value);
    if (!value) {
      const queued = pending.current;
      pending.current = [];
      queued.forEach(apply);
    }
  }, [apply]);

  const s = store.current;
  return { entries: s.entries, fields: [...s.fields.values()], size: s.size, up, paused, setPaused };
}
