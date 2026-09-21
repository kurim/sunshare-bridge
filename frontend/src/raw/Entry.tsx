import { memo, useState } from "react";
import { useT } from "../i18n";
import { hms } from "../lib";
import type { ParsedEntry } from "./useRawLog";

const ms = (t: number) => `${hms(t)}.${String(Math.floor((t % 1) * 1000)).padStart(3, "0")}`;

function summary(e: ParsedEntry, empty: string): string {
  if (!e.obj) return e.body.replace(/\s+/g, " ").slice(0, 160) || empty;
  return Object.entries(e.obj).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ");
}

const statusClass = (s: number | null) => (s == null ? "" : s < 300 ? "ok" : "bad");

/** One push. Only the one-line summary is rendered up front; the (much larger) body opens on demand. */
export const Entry = memo(function Entry({ entry: e, respStatus, respBody }: {
  entry: ParsedEntry; respStatus: number | null; respBody: string | null;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <details className="entry" onToggle={(ev) => setOpen(ev.currentTarget.open)}>
      <summary>
        <span className="et">{ms(e.t)}</span>
        <span className="es">{summary(e, t("rw.empty"))}</span>
        {!e.obj && <span className="tag bad">{t("rw.notJson")}</span>}
        <span className={`tag ${statusClass(respStatus)}`}>{respStatus ?? "…"}</span>
      </summary>
      {open && (
        <div className="eb">
          <span className="label">
            {t("rw.body", { size: e.size, truncated: e.truncated ? t("rw.truncated") : "", method: e.method, path: e.path, from: e.remote ?? "?" })}
          </span>
          <pre>{e.obj ? JSON.stringify(e.obj, null, 2) : e.body}</pre>
          <span className="label">{t("rw.headers")}</span>
          <pre>{Object.entries(e.headers).map(([k, v]) => `${k}: ${v}`).join("\n") || "–"}</pre>
          <span className="label">{t("rw.response")}</span>
          <pre>{respStatus == null ? t("rw.pending") : `${respStatus}\n${respBody ?? ""}`}</pre>
        </div>
      )}
    </details>
  );
});
