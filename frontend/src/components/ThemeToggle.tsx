import { useI18n, type Key } from "../i18n";
import { THEMES, useTheme, type Theme } from "../theme";
import { Icon, type IconName } from "./Icons";

const ICON: Record<Theme, IconName> = { auto: "themeAuto", light: "sun", dark: "moon" };
const LABEL: Record<Theme, Key> = { auto: "theme.auto", light: "theme.light", dark: "theme.dark" };

/** One button that cycles auto → light → dark; the icon shows the current choice. */
export function ThemeToggle() {
  const { t } = useI18n();
  const [theme, setTheme] = useTheme();
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  return (
    <button type="button" className="link icon-btn" data-theme-mode={theme}
      title={t("theme.current", { mode: t(LABEL[theme]) })}
      aria-label={t("theme.switch", { mode: t(LABEL[next]) })}
      onClick={() => setTheme(next)}>
      <Icon name={ICON[theme]} />
    </button>
  );
}
