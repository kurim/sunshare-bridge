import { useState } from "react";
import type { Settings } from "./api";
import { ControllerCard } from "./control/ControllerCard";
import { DeviceCard } from "./control/DeviceCard";
import { EnvCard } from "./control/EnvCard";
import { PlanPreview } from "./control/PlanPreview";
import { SettingsCard } from "./control/SettingsCard";
import { useT } from "./i18n";
import { useLiveData } from "./live";

export function Control() {
  const t = useT();
  const { reading, control: status, controlError: error, setControl: apply } = useLiveData();
  const [preview, setPreview] = useState<Settings | null>(null);

  if (!status) return <p className={error ? "error" : "hint"}>{error ? t("app.unreachable") : t("app.loading")}</p>;
  return (
    <div className="control-page">
      {error && <p className="error" role="alert">{t("app.unreachable")}</p>}
      <div className="control-grid">
        <div className="col">
          <ControllerCard status={status} onStatus={apply} />
          <DeviceCard status={status} onStatus={apply} />
        </div>
        <div className="col">
          <SettingsCard status={status} onStatus={apply} onPreview={setPreview} />
          <PlanPreview settings={preview ?? status.settings} soc={reading?.soc ?? null} />
        </div>
      </div>
      <EnvCard />
    </div>
  );
}
