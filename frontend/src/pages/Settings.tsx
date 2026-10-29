import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";

type Settings = {
  company_name: string;
  grace_minutes: number;
  working_days: string;
  timezone: string;
  sync_retries: number;
  dormant_after_days: number;
  punch_debounce_minutes: number;
  max_session_hours: number;
  retap_window_minutes: number;
  default_start: string;
  default_end: string;
  agent_token: string;
  using_default_admin_password: boolean;
};

export function SettingsPage({ mustChange = false }: { mustChange?: boolean }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api<Settings>("/api/v1/settings").then(setSettings).catch((err) => setError(err.message));
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) return;
    setError("");
    try {
      const next = await api<Settings & { recalculated_sessions?: number | null }>("/api/v1/settings", { method: "PUT", body: JSON.stringify(settings) });
      setSettings(next);
      setNotice(
        typeof next.recalculated_sessions === "number"
          ? `Settings saved. Attendance was recalculated from the stored punches (${next.recalculated_sessions} sessions).`
          : "Settings saved.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  async function password(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const me = await api<{ user: { id: number } }>("/api/v1/auth/me");
    setError("");
    try {
      await api(`/api/v1/users/${me.user.id}`, { method: "PATCH", body: JSON.stringify({ password: data.get("password") }) });
      setNotice("Password updated.");
      form.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update password");
    }
  }

  async function backup() {
    setError("");
    try {
      const body = await api<{ sqlite: string; json: string }>("/api/v1/settings/backup", { method: "POST" });
      setNotice(`Backup written. Database: ${body.sqlite || "not a SQLite file"}. Snapshot: ${body.json}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backup failed");
    }
  }

  if (!settings) return error ? <p className="error">{error}</p> : <p>Loading…</p>;
  return (
    <>
      <div className="top"><div><h1>Settings</h1><p className="lede">Company rules used when a branch does not set its own.</p></div></div>
      {mustChange ? <p className="banner">The administrator password is still the default. Change it before this system is used.</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <form className="panel form-grid" onSubmit={save}>
        <label className="field">Company<input value={settings.company_name} onChange={(e) => setSettings({ ...settings, company_name: e.target.value })} /></label>
        <label className="field">Grace minutes<input type="number" value={settings.grace_minutes} onChange={(e) => setSettings({ ...settings, grace_minutes: Number(e.target.value) })} /></label>
        <label className="field">Working days<input value={settings.working_days} onChange={(e) => setSettings({ ...settings, working_days: e.target.value })} /></label>
        <label className="field">Timezone<input value={settings.timezone} onChange={(e) => setSettings({ ...settings, timezone: e.target.value })} /></label>
        <label className="field">Default start<input value={settings.default_start} onChange={(e) => setSettings({ ...settings, default_start: e.target.value })} /></label>
        <label className="field">Default end<input value={settings.default_end} onChange={(e) => setSettings({ ...settings, default_end: e.target.value })} /></label>
        <label className="field">Sync retries<input type="number" value={settings.sync_retries} onChange={(e) => setSettings({ ...settings, sync_retries: Number(e.target.value) })} /></label>
        <label className="field">
          Ignore repeat taps within (minutes)
          <input type="number" min={0} max={30} step="0.5" value={settings.punch_debounce_minutes} onChange={(e) => setSettings({ ...settings, punch_debounce_minutes: Number(e.target.value) })} />
          <small>A terminal often records one tap twice, seconds apart. The second record stays stored and is not counted.</small>
        </label>
        <label className="field">
          Treat a second check-in or check-out as a re-tap within (minutes)
          <input type="number" min={0} max={240} step="5" value={settings.retap_window_minutes} onChange={(e) => setSettings({ ...settings, retap_window_minutes: Number(e.target.value) })} />
          <small>If someone taps again with the same in/out flag within this time, only the first tap counts. This stops 09:05 and 09:07 from becoming a two-minute session. Use 0 to turn it off.</small>
        </label>
        <label className="field">
          Longest single session (hours)
          <input type="number" min={1} max={24} step="0.5" value={settings.max_session_hours} onChange={(e) => setSettings({ ...settings, max_session_hours: Number(e.target.value) })} />
          <small>If the next punch is later than this, the first punch is treated as a missing check-out. Changing this or the repeat-tap window recalculates all attendance.</small>
        </label>
        <label className="field">
          Report people active within (days)
          <input type="number" min={0} value={settings.dormant_after_days} onChange={(e) => setSettings({ ...settings, dormant_after_days: Number(e.target.value) })} />
          <small>People on a terminal with no punch in this many days before the end of a report are left out, so former staff are not listed as absent. Use 0 to list everyone.</small>
        </label>
        <button className="btn" type="submit">Save</button>
      </form>
      <form className="panel form-grid" style={{ marginTop: 14 }} onSubmit={password}>
        <h2 style={{ gridColumn: "1 / -1" }}>Administrator password</h2>
        <label className="field">New password<input name="password" type="password" minLength={8} required /></label>
        <button className="btn" type="submit">Update password</button>
      </form>
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Branch agent</h2>
        <p>A machine on a private branch network can pull the terminal and post logs with this token. The cloud server still cannot reach a private IP by itself.</p>
        <code>{settings.agent_token}</code>
        <div className="row-actions" style={{ marginTop: 12 }}>
          <button className="btn ghost" type="button" onClick={() => api<{ agent_token: string }>("/api/v1/settings/rotate-agent-token", { method: "POST" }).then((body) => setSettings({ ...settings, agent_token: body.agent_token }))}>Rotate token</button>
          <button className="btn ghost" type="button" onClick={backup}>Back up database</button>
        </div>
      </section>
    </>
  );
}
