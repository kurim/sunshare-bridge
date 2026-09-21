import { useCallback, useEffect, useState } from "react";

/** auto = follow the system ("reduce motion"), on / off = the user's own choice. */
export type Motion = "auto" | "on" | "off";

const KEY = "motion";
const isMotion = (v: unknown): v is Motion => v === "auto" || v === "on" || v === "off";
const reducedQuery = () => window.matchMedia("(prefers-reduced-motion: reduce)");

export function storedMotion(): Motion {
  try { const v = localStorage.getItem(KEY); if (isMotion(v)) return v; } catch { /* private mode */ }
  return "auto";
}

/** The stylesheet reads `data-motion`; without it the system setting decides. */
export function applyMotion(pref: Motion) {
  const root = document.documentElement;
  if (pref === "auto") delete root.dataset.motion;
  else root.dataset.motion = pref;
}

export function useMotion() {
  const [pref, setPrefState] = useState<Motion>(storedMotion);
  const [systemReduced, setSystemReduced] = useState(() => reducedQuery().matches);

  useEffect(() => {
    const query = reducedQuery();
    const onChange = () => setSystemReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  useEffect(() => applyMotion(pref), [pref]);

  const setPref = useCallback((next: Motion) => {
    try { localStorage.setItem(KEY, next); } catch { /* private mode */ }
    setPrefState(next);
  }, []);
  const active = pref === "on" || (pref === "auto" && !systemReduced);
  return { pref, setPref, active, systemReduced };
}
