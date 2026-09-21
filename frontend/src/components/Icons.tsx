const PATHS = {
  overview: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
  flow: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  telemetry: <><path d="M4 19V5" /><path d="M4 19h16" /><path d="M8 15l3-4 3 2 4-6" /></>,
  control: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></>,
  raw: <><path d="M4 6h16M4 12h10M4 18h13" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  themeAuto: <><circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" /></>,
  battery: <><rect x="2" y="7" width="17" height="10" rx="2" /><path d="M22 11v2" /><path d="M6 12h5" /></>,
  inverter: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M6.5 14c1.3-4.5 3-4.5 4.3 0s3 4.5 4.3 0" /><path d="M18 9h.01" /></>,
  house: <><path d="M3 11l9-8 9 8" /><path d="M5 9.5V20h14V9.5" /><path d="M10 20v-5h4v5" /></>,
  plug: <><path d="M9 2v6M15 2v6" /><path d="M6 8h12v3a6 6 0 0 1-12 0z" /><path d="M12 17v5" /></>,
  gauge: <><path d="M4.5 18a9 9 0 1 1 15 0" /><path d="M12 14l4-5" /><circle cx="12" cy="14" r="1" /></>,
  grid: <><path d="M12 2l-5 20M12 2l5 20" /><path d="M8.5 9h7M7 14h10" /><path d="M4 7h16" /></>,
  play: <path d="M7 4.5v15l12-7.5z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  bolt: <path d="M13 2L4 14h7l-1 8 9-12h-7z" />,
  arrowDown: <path d="M12 4v16M6 14l6 6 6-6" />,
  logout: <><path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" /><path d="M16 8l4 4-4 4M20 12H9" /></>,
} as const;

export type IconName = keyof typeof PATHS;

/** Battery whose fill follows the state of charge (the colour is set by the caller through `color`). */
export function BatteryIcon({ soc }: { soc: number | null }) {
  const level = soc == null ? 0 : Math.max(0, Math.min(100, soc));
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="7" width="17" height="10" rx="2" />
      <path d="M22 11v2" />
      {level > 0 && <rect x="4" y="9" width={Math.max(0.6, 13 * level / 100)} height="6" rx="0.8" fill="currentColor" stroke="none" />}
    </svg>
  );
}

export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
