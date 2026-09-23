/**
 * Runtime equivalent of Vite's build-time BASE_URL: the app's own routes always mount at a
 * literal "/app" segment (see app/spa.py's BASE), but what precedes it varies - "" standalone,
 * "/api/hassio_ingress/<token>" under Home Assistant Ingress. The Ingress token is only known at
 * runtime (per install), so unlike the old build-time constant this is computed once from the
 * page's own URL, which the browser already resolved correctly to load us.
 */
export function computeBasePath(pathname: string): string {
  const idx = pathname.indexOf("/app/");
  if (idx >= 0) return pathname.slice(0, idx) + "/app";
  if (pathname.endsWith("/app")) return pathname; // the bare "/app" redirect route itself
  return "/app"; // dev server / unexpected path: today's fixed behaviour
}

// `typeof window` guard: this module is also imported by the Node test runner, which has no DOM.
export const BASE_PATH = typeof window !== "undefined" ? computeBasePath(window.location.pathname) : "/app";

/** BASE_PATH with the trailing "/app" stripped - the prefix in front of sibling "/api/..." routes. */
export const API_BASE = BASE_PATH.replace(/\/app$/, "") + "/api";
