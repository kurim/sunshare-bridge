import { API_BASE } from "./basePath";

export class Unauthorized extends Error {}

/** A failed API call; `message` is the server's (German) text, `status` and `retryAfter` are language-neutral. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly retryAfter: number | null, readonly msg: Msg | null = null) {
    super(message);
  }
}

/** A status or error text of the bridge as key + parameters (see app/messages.py); the UI translates it. */
export interface Msg {
  key: string;
  level: "info" | "ok" | "warn" | "error";
  params: Record<string, string | number | null | Msg>;
}

export interface Me {
  auth_required: boolean;
  authenticated: boolean;
  user: string | null;
  version: string;
  /** Served through Home Assistant's Ingress proxy - the only way in already, so the
   * "set up a login" warning (meant for a directly reachable UI) doesn't apply. */
  ingress: boolean;
}

/** One merged live reading (W, kWh and %; the bridge adds `_t` = epoch seconds and `_eff*` = efficiency baseline). */
export interface Reading {
  _t?: number;
  source?: string;
  soc?: number | null;
  pvPow?: number | null;
  pvPreal?: number | null;
  pv1Pow?: number | null;
  pv2Pow?: number | null;
  batPow?: number | null;
  batPreal?: number | null;
  invPow?: number | null;
  loadPow?: number | null;
  offGridPow?: number | null;
  gridPow?: number | null;
  exportPow?: number | null;
  meterPow?: number | null;
  _meterT?: number | null;
  todayEnergyKwh?: number | null;
  lifetimeEnergyKwh?: number | null;
  pvPeakTodayW?: number | null;
  pvEnergyTodayKwh?: number | null;
  pvEnergyTotalKwh?: number | null;
  batChargeEnergyKwh?: number | null;
  batDischargeEnergyKwh?: number | null;
  _effBaseT?: number | null;
  _effBaseSoc?: number | null;
  _effBaseChargeKwh?: number | null;
  _effBaseDischargeKwh?: number | null;
}

export interface HistoryLong {
  step: number;
  enabled: boolean;
  retention_days: number;
  rows: Reading[];
}

export interface CloudLogin {
  ok: boolean;
  error: Msg | null;
  retry_in_s: number | null;
}

export type Settings = Record<string, string | number>;

export interface ControlStatus {
  cloud_login: CloudLogin | null;
  plan: boolean;
  cover_load: boolean;
  adaptive_gain: boolean;
  gain: number;
  phase: Msg | null;
  est_full_h: number | null;
  est_night_h: number | null;
  enabled: boolean;
  dry_run: boolean;
  meter_w: number | null;
  meter_age_s: number | null;
  inverter_w: number | null;
  setpoint_w: number | null;
  restore_w: number | null;
  target_w: number;
  state_topic: string | null;
  mqtt_connected: boolean;
  config_seen: boolean;
  value_path: string | null;
  last_payload: string | null;
  last_action: Msg | null;
  settings: Settings;
  defaults: Settings;
  battery_full: boolean;
  control_max_w: number;
  account: "main" | "guest";
  min_soc_source: "device" | "bridge";
  device_limits: { soc_min: number | null; soc_max: number | null; country_max_power: number | null } | null;
  device_note: Msg | null;
}

export interface ControlUpdate {
  enabled?: boolean;
  dry_run?: boolean;
  plan?: boolean;
  cover_load?: boolean;
  adaptive_gain?: boolean;
  settings?: Settings;
  device?: { COUNTRY_MAX_POWER: number };
}

/** One day's coarse PV outlook from OpenWeatherMap (see app/weather.py); null while data for
 * that day isn't available (e.g. "tomorrow" late in the forecast window). */
export interface WeatherDay {
  clouds_pct: number;
  pop_pct: number;
  outlook: "sunny" | "partly" | "cloudy";
}
export interface WeatherStatus {
  available: boolean;
  today: WeatherDay | null;
  tomorrow: WeatherDay | null;
  updated_at: number | null;
  error: string | null;
}

export interface EnvItem {
  key: string;
  value: string;
  secret: boolean;
  source: "env" | "default" | "unset";
}
export interface EnvGroup {
  id: string;
  title: string;
  items: EnvItem[];
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(API_BASE + path.slice("/api".length), {
    credentials: "same-origin",
    ...init,
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (res.status === 401 && !path.startsWith("/api/auth/")) throw new Unauthorized();
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const wait = Number(res.headers.get("Retry-After"));
    const { error, msg } = body as { error?: string; msg?: Msg };
    throw new ApiError(error ?? res.statusText, res.status, wait > 0 ? wait : null, msg ?? null);
  }
  return body as T;
}

export const getMe = () => api<Me>("/api/auth/me");
export const login = (user: string, password: string) =>
  api<Me>("/api/auth/login", { method: "POST", body: JSON.stringify({ user, password }) });
export const logout = () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
export const getControl = () => api<ControlStatus>("/api/control");
export const postControl = (update: ControlUpdate) =>
  api<ControlStatus>("/api/control", { method: "POST", body: JSON.stringify(update) });
export const getEnv = () => api<EnvGroup[]>("/api/env");
export const getWeather = () => api<WeatherStatus>("/api/weather");

export const getHistoryCompact = () => api<Reading[]>("/api/history?compact=1");
/** A rolling window (`{ minutes }`, e.g. "last 24h") or an actual local calendar day
 * (`{ range: "today" | "yesterday" }`, see app/main.py's get_history_long). */
export type HistorySpec = { minutes: number } | { range: "today" | "yesterday" };
export const getHistoryLong = (spec: HistorySpec) =>
  api<HistoryLong>(`/api/history/long?${"minutes" in spec ? `minutes=${spec.minutes}` : `range=${spec.range}`}`);

/** One push of the inverter to the telemetry endpoint, byte-for-byte (the bridge redacts auth headers). */
export interface RawEntry {
  id: number;
  t: number;
  method: string;
  path: string;
  remote: string | null;
  headers: Record<string, string>;
  size: number;
  body: string;
  truncated: boolean;
  resp_status: number | null;
  resp_body: string | null;
}

export type RawEvent =
  | { type: "hello"; last_id: number; size: number }
  | { type: "add"; entry: RawEntry }
  | { type: "resp"; id: number; resp_status: number; resp_body: string | null }
  | { type: "clear" };

export const getRaw = () => api<RawEntry[]>("/api/raw");
export const clearRaw = () => api<{ ok: boolean }>("/api/raw/clear", { method: "POST" });
