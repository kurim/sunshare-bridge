import type { Settings } from "../api";
import type { Translate } from "../i18n";

export interface Field {
  key: string;
  unit?: string;
  kind: "number" | "range" | "time";
  min?: number;
  max?: number;
  step?: number;
}

// Labels and help texts live in the language files as `field.<KEY>` and `field.<KEY>.help`.
export const FIELDS: Field[] = [
  { key: "BATTERY_CAPACITY_WH", unit: "Wh", kind: "number", min: 100, max: 100000, step: 1 },
  { key: "CHARGE_RESERVE_W", unit: "W", kind: "number", min: 0, max: 2000, step: 10 },
  { key: "CHARGE_FULL_SOC", unit: "%", kind: "range", min: 50, max: 100, step: 1 },
  { key: "CHARGE_RELEASE_SOC", unit: "%", kind: "range", min: 50, max: 100, step: 1 },
  { key: "NIGHT_START", kind: "time" },
  { key: "NIGHT_END", kind: "time" },
  { key: "NIGHT_MAX_W", unit: "W", kind: "number", min: 0, max: 2000, step: 10 },
  { key: "NIGHT_MIN_SOC", unit: "%", kind: "range", min: 0, max: 100, step: 1 },
  { key: "CONTROL_METER_MAX_AGE", unit: "s", kind: "number", min: 5, max: 3600, step: 5 },
  { key: "CONTROL_FALLBACK_W", unit: "W", kind: "number", min: 0, max: 2000, step: 10 },
];

export type Form = Record<string, string>;

export const toForm = (settings: Settings): Form =>
  Object.fromEntries(FIELDS.map((f) => [f.key, String(settings[f.key] ?? "")]));

/** First problem in the form, or null. Mirrors the checks of the bridge (which validates again). */
export function validate(form: Form, t: Translate): { key: string; text: string } | null {
  for (const f of FIELDS) {
    const raw = form[f.key];
    if (f.kind === "time") {
      if (!/^\d{2}:\d{2}$/.test(raw)) return { key: f.key, text: t("sc.v.time", { key: f.key }) };
      continue;
    }
    const v = Number(raw);
    if (raw === "" || Number.isNaN(v) || v < f.min! || v > f.max!) {
      return { key: f.key, text: t("sc.v.range", { key: f.key, min: f.min!, max: f.max! }) };
    }
  }
  if (Number(form.CHARGE_RELEASE_SOC) > Number(form.CHARGE_FULL_SOC)) {
    return { key: "CHARGE_RELEASE_SOC", text: t("sc.v.release") };
  }
  return null;
}

/** What the plan preview shows: the form value where it is valid, otherwise the saved one. */
export function effective(saved: Settings, form: Form, dirty: boolean): Settings {
  if (!dirty) return saved;
  const out: Settings = { ...saved };
  for (const f of FIELDS) {
    const raw = form[f.key];
    if (f.kind === "time") { if (/^\d{2}:\d{2}$/.test(raw)) out[f.key] = raw; }
    else if (raw !== "" && !Number.isNaN(Number(raw))) out[f.key] = Number(raw);
  }
  return out;
}

export function toPayload(form: Form): Settings {
  return Object.fromEntries(FIELDS.map((f) => [f.key, f.kind === "time" ? form[f.key] : Number(form[f.key])]));
}
