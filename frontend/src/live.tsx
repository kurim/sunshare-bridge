import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  getControl, getHistoryCompact, getMe, getWeather, Unauthorized,
  type ControlStatus, type Reading, type WeatherStatus,
} from "./api";
import { API_BASE } from "./basePath";

export type LiveState = "connecting" | "live" | "offline";

const HISTORY_MAX = 600; // same size as the bridge's in-memory buffer
const WEATHER_POLL_MS = 600_000; // the forecast itself only updates every ~3h upstream

interface LiveData {
  reading: Reading | null;
  /** Recent readings (oldest first) for the live charts. */
  history: Reading[];
  mode: string | null;
  state: LiveState;
  control: ControlStatus | null;
  controlError: boolean;
  /** Put a fresh status (e.g. the answer to a POST) straight into the view. */
  setControl: (status: ControlStatus) => void;
  weather: WeatherStatus | null;
}

const Ctx = createContext<LiveData | null>(null);

export function useLiveData(): LiveData {
  const value = useContext(Ctx);
  if (!value) throw new Error("useLiveData outside of LiveProvider");
  return value;
}

/**
 * One live stream, the recent history and the controller status for the whole app.
 * While the tab is hidden the stream is closed and the polling stops (a phone in the pocket
 * should not keep a connection and the radio busy); coming back re-opens it and closes the gap.
 */
export function LiveProvider({ children, onSessionEnded }: { children: ReactNode; onSessionEnded: () => void }) {
  const [reading, setReading] = useState<Reading | null>(null);
  const [history, setHistory] = useState<Reading[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [state, setState] = useState<LiveState>("connecting");
  const [control, setControl] = useState<ControlStatus | null>(null);
  const [controlError, setControlError] = useState(false);
  const [weather, setWeather] = useState<WeatherStatus | null>(null);

  const refreshControl = useCallback(() => {
    getControl()
      .then((s) => { setControl(s); setControlError(false); })
      .catch((err) => {
        if (err instanceof Unauthorized) onSessionEnded();
        else setControlError(true);
      });
  }, [onSessionEnded]);

  const refreshWeather = useCallback(() => {
    getWeather()
      .then(setWeather)
      .catch((err) => { if (err instanceof Unauthorized) onSessionEnded(); });
  }, [onSessionEnded]);

  const loadHistory = useCallback(() => {
    getHistoryCompact()
      .then((rows) => {
        const lastT = rows.length ? rows[rows.length - 1]._t ?? 0 : 0;
        // Readings that arrived over the stream meanwhile come after `rows`.
        setHistory((prev) => rows.concat(prev.filter((r) => (r._t ?? 0) > lastT)).slice(-HISTORY_MAX));
      })
      .catch((err) => { if (err instanceof Unauthorized) onSessionEnded(); });
  }, [onSessionEnded]);

  useEffect(() => {
    let source: EventSource | null = null;

    const open = () => {
      if (source || document.hidden) return;
      setState("connecting");
      source = new EventSource(`${API_BASE}/stream`);
      source.onmessage = (event) => {
        const data = JSON.parse(event.data) as { mode?: string; reading?: Reading | null };
        if (data.mode) setMode(data.mode);
        const r = data.reading;
        if (r) {
          setReading(r);
          setHistory((prev) => (prev.length && prev[prev.length - 1]._t === r._t ? prev : [...prev.slice(-(HISTORY_MAX - 1)), r]));
        }
        setState("live");
      };
      source.onerror = () => {
        setState("offline");
        getMe().then((me) => { if (!me.authenticated) onSessionEnded(); }).catch(() => undefined);
      };
    };
    const close = () => { source?.close(); source = null; };

    const onVisibility = () => {
      if (document.hidden) { close(); return; }
      open();
      loadHistory();
      refreshControl();
      refreshWeather();
    };

    open();
    loadHistory();
    refreshControl();
    refreshWeather();
    const poll = setInterval(() => { if (!document.hidden) refreshControl(); }, 5000);
    const weatherPoll = setInterval(() => { if (!document.hidden) refreshWeather(); }, WEATHER_POLL_MS);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", close);
    return () => {
      clearInterval(poll);
      clearInterval(weatherPoll);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", close);
      close();
    };
  }, [onSessionEnded, loadHistory, refreshControl, refreshWeather]);

  return <Ctx.Provider value={{ reading, history, mode, state, control, controlError, setControl, weather }}>{children}</Ctx.Provider>;
}
