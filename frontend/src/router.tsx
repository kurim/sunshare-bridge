import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { BASE_PATH as BASE } from "./basePath";

/** Path below /app ("/" for the start page). */
const current = () => window.location.pathname.slice(BASE.length).replace(/\/+$/, "") || "/";

export function usePath(): string {
  const [path, setPath] = useState(current);
  useEffect(() => {
    const onPop = () => setPath(current());
    window.addEventListener("popstate", onPop);
    window.addEventListener("app:navigate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("app:navigate", onPop);
    };
  }, []);
  return path;
}

export function navigate(to: string) {
  window.history.pushState(null, "", BASE + (to === "/" ? "/" : to));
  window.dispatchEvent(new Event("app:navigate"));
  window.scrollTo(0, 0);
}

export function Link({ to, className, children }: { to: string; className?: string; children: ReactNode }) {
  const onClick = (event: MouseEvent) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return; // new tab etc.
    event.preventDefault();
    navigate(to);
  };
  return <a href={BASE + (to === "/" ? "/" : to)} className={className} onClick={onClick}>{children}</a>;
}
