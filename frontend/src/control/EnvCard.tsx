import { useEffect, useState } from "react";
import { getEnv, type EnvGroup } from "../api";
import { useT, type Key } from "../i18n";

export function EnvCard() {
  const t = useT();
  const [groups, setGroups] = useState<EnvGroup[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => { getEnv().then(setGroups).catch(() => setFailed(true)); }, []);

  return (
    <details className="card">
      <summary className="card-head">
        <div><h2>{t("env.title")}</h2><p className="hint">{t("env.subtitle")}</p></div>
        <span className="tag">{t("env.readonly")}</span>
      </summary>
      {failed && <p className="error">{t("env.failed")}</p>}
      {!groups && !failed && <p className="hint">{t("env.loading")}</p>}
      <div className="env-grid">
        {groups?.map((g) => (
          <div key={g.id} className="env-group">
            <h3>{t(`env.group.${g.id}` as Key)}</h3>
            {g.items.map((i) => (
              <div key={i.key} className="env-row">
                <code>{i.key}</code>
                <span className="env-value">
                  {i.source === "default" && <span className="tag">{t("env.default")}</span>}
                  <span className={i.secret && i.value ? "mask" : i.source === "unset" || i.value === "" ? "unset" : ""}>
                    {i.value === "" ? (i.source === "unset" ? t("env.unset") : "–") : i.value}
                  </span>
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}
