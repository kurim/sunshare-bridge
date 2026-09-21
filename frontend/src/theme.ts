import { useCallback, useEffect, useState } from "react";

export type Theme = "auto" | "light" | "dark";
export const THEMES: Theme[] = ["auto", "light", "dark"];

const KEY = "theme";
const isTheme = (v: unknown): v is Theme => v === "auto" || v === "light" || v === "dark";
const prefersDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

export function storedTheme(): Theme {
  try { const v = localStorage.getItem(KEY); if (isTheme(v)) return v; } catch { /* private mode */ }
  return "auto";
}

/** "auto" removes the attribute, so the stylesheet follows the system setting by itself. */
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "auto") delete root.dataset.theme;
  else root.dataset.theme = theme;
  // Browser / PWA title bar colour follows the chosen look.
  const dark = theme === "dark" || (theme === "auto" && prefersDark());
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#17222d" : "#ffffff");
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(storedTheme);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "auto") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("auto"); // the system switched (e.g. at sunset)
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    try { localStorage.setItem(KEY, next); } catch { /* private mode */ }
    setThemeState(next);
  }, []);
  return [theme, setTheme];
}
