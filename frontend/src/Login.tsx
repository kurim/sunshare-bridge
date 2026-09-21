import { useState, type FormEvent } from "react";
import { ApiError, login } from "./api";
import { useT } from "./i18n";

export function Login({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(user, password);
      onDone();
    } catch (err) {
      // The server's texts are German; the client maps the status codes to its own language.
      if (err instanceof ApiError && err.status === 401) setError(t("login.wrong"));
      else if (err instanceof ApiError && err.status === 429) setError(t("login.tooMany", { s: err.retryAfter ?? 60 }));
      else setError(t("login.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>{t("app.title")} Bridge</h1>
        <label>
          {t("login.user")}
          <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoCapitalize="none" required />
        </label>
        <label>
          {t("login.password")}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? t("login.busy") : t("login.submit")}</button>
      </form>
    </main>
  );
}
