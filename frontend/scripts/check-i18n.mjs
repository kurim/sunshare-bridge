// Every language file must have the same keys as de.ts (TypeScript checks that too) and use the same
// {placeholders} in every message; a missing one would show up as literal "{n}" in the UI.
import { readdirSync, readFileSync } from "node:fs";

const dir = new URL("../src/i18n/", import.meta.url);
const parse = (file) => {
  const messages = new Map();
  for (const m of readFileSync(new URL(file, dir), "utf8").matchAll(/^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/gm)) messages.set(m[1], m[2]);
  return messages;
};
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

const base = parse("de.ts");
let problems = 0;
for (const file of readdirSync(dir).filter((f) => /^[a-z]{2}\.ts$/.test(f) && f !== "de.ts")) {
  const other = parse(file);
  for (const [key, text] of base) {
    if (!other.has(key)) { console.error(`${file}: missing key "${key}"`); problems++; }
    else if (placeholders(text) !== placeholders(other.get(key))) {
      console.error(`${file}: "${key}" has other placeholders (${placeholders(other.get(key))}) than de.ts (${placeholders(text)})`);
      problems++;
    }
  }
  for (const key of other.keys()) if (!base.has(key)) { console.error(`${file}: unknown key "${key}"`); problems++; }
}
if (problems) process.exit(1);
console.log(`i18n ok: ${base.size} keys`);
