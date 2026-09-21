import { createContext, Fragment, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Msg } from "../api";
import { setFormatLocale } from "../format";
import { de, type Messages } from "./de";
import { en } from "./en";

/**
 * Adding a language: copy `en.ts` to `<code>.ts`, translate the values, register it below (name shown
 * in the switcher + BCP 47 tag for number formatting). The build fails if a key is missing.
 */
export type Key = keyof Messages;
const CATALOGS = { de: de as Messages, en } satisfies Record<string, Messages>;
export const LANGUAGES = { de: { name: "Deutsch", tag: "de-DE" }, en: { name: "English", tag: "en-GB" } } as const;
export type Lang = keyof typeof LANGUAGES;

export type Translate = (key: Key, params?: Record<string, string | number>) => string;

const STORAGE_KEY = "lang";
const isLang = (v: unknown): v is Lang => typeof v === "string" && v in LANGUAGES;

function detect(): Lang {
  try { const s = localStorage.getItem(STORAGE_KEY); if (isLang(s)) return s; } catch { /* private mode */ }
  const nav = navigator.language?.slice(0, 2);
  return isLang(nav) ? nav : "de";
}

interface I18n { lang: Lang; setLang: (lang: Lang) => void; t: Translate; tm: (msg: Msg) => string }
const Ctx = createContext<I18n | null>(null);

export function useI18n(): I18n {
  const value = useContext(Ctx);
  if (!value) throw new Error("useI18n outside of I18nProvider");
  return value;
}
export const useT = (): Translate => useI18n().t;
/** Translates a message of the bridge (key + parameters, nested messages included). */
export const useMsg = (): ((msg: Msg) => string) => useI18n().tm;

const isMsg = (v: unknown): v is Msg => typeof v === "object" && v !== null && "key" in v;

function translateMsg(t: Translate, msg: Msg): string {
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(msg.params)) {
    params[name] = isMsg(value) ? translateMsg(t, value) : value ?? "–";
  }
  return t(`msg.${msg.key}` as Key, params);
}

function translator(lang: Lang): Translate {
  const messages = CATALOGS[lang];
  return (key, params) => {
    const text = messages[key] ?? CATALOGS.de[key] ?? key;
    return params ? text.replace(/\{(\w+)\}/g, (m, name: string) => String(params[name] ?? m)) : text;
  };
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detect);
  setFormatLocale(LANGUAGES[lang].tag); // before the children render, they format numbers with it

  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const value = useMemo<I18n>(() => {
    const t = translator(lang);
    return {
    lang,
    t,
    tm: (msg: Msg) => translateMsg(t, msg),
    setLang: (next: Lang) => { try { localStorage.setItem(STORAGE_KEY, next); } catch { /* private mode */ } setLangState(next); },
    };
  }, [lang]);

  // A new key remounts the tree: everything, including plain number formatting, is re-rendered in the new language.
  return <Ctx.Provider value={value}><Fragment key={lang}>{children}</Fragment></Ctx.Provider>;
}
