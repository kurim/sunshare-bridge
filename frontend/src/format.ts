let locale = "de-DE";
/** Set by the i18n provider; numbers are formatted with the decimal separator of the chosen language. */
export const setFormatLocale = (tag: string) => { locale = tag; };

/** A non-breaking space joins number and unit, so "63 %" never wraps between them.
 *  `fixed` keeps trailing zeros (1.20 instead of 1.2), for values that read as a measurement. */
export const fmt = (v: number | null | undefined, unit = "", digits = 0, fixed = false): string =>
  v === null || v === undefined
    ? "–"
    : `${v.toLocaleString(locale, { minimumFractionDigits: fixed ? digits : 0, maximumFractionDigits: digits })}${unit ? `\u00a0${unit}` : ""}`;
