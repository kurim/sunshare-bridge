import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import { applyMotion, storedMotion } from "./motion";
import { applyTheme, storedTheme } from "./theme";

applyTheme(storedTheme());
applyMotion(storedMotion());
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

// Offline-capable app shell (needs https or localhost; skipped in `npm run dev`).
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(() => undefined);
}
