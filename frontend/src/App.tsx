import { useCallback, useEffect, useState } from "react";
import { getMe, logout, type Me } from "./api";
import { Icon, type IconName } from "./components/Icons";
import { ThemeToggle } from "./components/ThemeToggle";
import { Control } from "./Control";
import { Flow } from "./Flow";
import { useNow } from "./hooks";
import { I18nProvider, LANGUAGES, useI18n, type Key, type Lang } from "./i18n";
import { LiveProvider, useLiveData } from "./live";
import { Login } from "./Login";
import { Overview } from "./Overview";
import { Raw } from "./Raw";
import { Link, usePath } from "./router";
import { Telemetry } from "./Telemetry";

const TABS: { to: string; label: Key; icon: IconName }[] = [
  { to: "/", label: "nav.overview", icon: "overview" },
  { to: "/flow", label: "nav.flow", icon: "flow" },
  { to: "/telemetry", label: "nav.telemetry", icon: "telemetry" },
  { to: "/control", label: "nav.control", icon: "control" },
  { to: "/raw", label: "nav.raw", icon: "raw" },
];

function Page({ path, onSessionEnded }: { path: string; onSessionEnded: () => void }) {
  switch (path) {
    case "/flow": return <Flow />;
    case "/telemetry": return <Telemetry />;
    case "/control": return <Control />;
    case "/raw": return <Raw onSessionEnded={onSessionEnded} />;
    default: return <Overview />;
  }
}

function Shell({ me, onSessionEnded }: { me: Me; onSessionEnded: () => void }) {
  const { reading, mode, state } = useLiveData();
  const { t, lang, setLang } = useI18n();
  const path = usePath();
  const now = useNow(1000);
  const age = reading?._t ? Math.max(0, now - reading._t) : null;
  const status = state !== "live" ? (state === "connecting" ? "connecting" : "offline")
    : age != null && age < 15 ? "live" : age != null && age < 120 ? "stale" : "offline";
  const text = status === "live" ? t("conn.live", { mode: mode ?? "?" })
    : status === "stale" ? t("conn.stale") : status === "connecting" ? t("conn.connecting") : t("conn.offline");
  const known = TABS.some((tab) => tab.to === path);

  return (
    <>
      <header className="top">
        <h1>{t("app.title")}</h1>
        <nav className="tabs" aria-label={t("nav.label")}>
          {TABS.map((tab) => (
            <Link key={tab.to} to={tab.to} className={path === tab.to || (tab.to === "/" && !known) ? "active" : ""}>
              <Icon name={tab.icon} />
              <span>{t(tab.label)}</span>
            </Link>
          ))}
        </nav>
        <div className="top-right">
          <span className={`dot ${status}`} title={text} />
          <span className="hint conn-text">{text}</span>
          <ThemeToggle />
          <select className="lang" value={lang} aria-label={t("lang.label")} onChange={(e) => setLang(e.target.value as Lang)}>
            {Object.entries(LANGUAGES).map(([code, l]) => <option key={code} value={code}>{l.name}</option>)}
          </select>
          {me.auth_required && (
            <button className="link with-icon" onClick={() => logout().finally(onSessionEnded)} title={t("app.logout")}>
              <Icon name="logout" /><span className="logout-text">{t("app.logout")}</span>
            </button>
          )}
        </div>
      </header>
      <main className="page">
        {!me.auth_required && <p className="banner" role="note">{t("app.noLoginBanner")}</p>}
        <Page path={path} onSessionEnded={onSessionEnded} />
      </main>
    </>
  );
}

function Root() {
  const { t } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(() => {
    getMe().then((m) => { setMe(m); setFailed(false); }).catch(() => setFailed(true));
  }, []);
  useEffect(refresh, [refresh]);

  if (failed) return <main className="login"><p className="card error">{t("app.unreachable")} <button className="link" onClick={refresh}>{t("app.retry")}</button></p></main>;
  if (!me) return <main className="login"><p className="hint">{t("app.loading")}</p></main>;
  if (!me.authenticated) return <Login onDone={refresh} />;
  return <LiveProvider onSessionEnded={refresh}><Shell me={me} onSessionEnded={refresh} /></LiveProvider>;
}

export function App() {
  return <I18nProvider><Root /></I18nProvider>;
}
