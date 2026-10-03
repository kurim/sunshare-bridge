/** True in the installed app (home-screen icon, own window), false in a normal browser tab or the
 * Home Assistant ingress frame. Same test as the inline script in index.html. */
export interface PwaEnv {
  navigator: Navigator & { standalone?: boolean }; // `standalone` exists on iOS only
  matchMedia: Window["matchMedia"];
}

export function isStandalone(win: PwaEnv = window): boolean {
  return win.navigator.standalone === true || win.matchMedia("(display-mode: standalone)").matches;
}

/** Developer pages that only clutter the installed app's tab bar; still reachable by address. */
export const HIDDEN_IN_PWA: readonly string[] = ["/raw", "/debug"];
