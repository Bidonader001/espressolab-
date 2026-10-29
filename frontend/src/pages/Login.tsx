import { FormEvent, useState } from "react";
import { Logo } from "../Logo";

export function LoginPage({ onSubmit }: { onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void> }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <section className="login-story">
        <div>
          <Logo size="lg" />
          <h1>Attendance, from the machines you already have.</h1>
        </div>
        <p>Logs are read from ZKTeco terminals by IP. Nothing here recognizes a face or guesses a shift.</p>
      </section>
      <section className="login-form">
        <form
          className="login-card"
          onSubmit={async (event) => {
            setBusy(true);
            setError("");
            try {
              await onSubmit(event);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Sign-in failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          <h2>Sign in</h2>
          <label className="field">Username<input name="username" autoComplete="username" required /></label>
          <label className="field">Password<input name="password" type="password" autoComplete="current-password" required /></label>
          {error ? <p className="error">{error}</p> : null}
          <button className="btn" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </section>
    </div>
  );
}
