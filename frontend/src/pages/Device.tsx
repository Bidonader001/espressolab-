import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download, qs } from "../api";

type Device = {
  id: number; name: string; host: string; port: number; protocol: string; model: string; branch: string;
  connection_status: string; last_error: string; last_sync_at: string | null; last_sync_status: string;
  timeout_seconds: number; sync_interval_minutes: number; simulated: boolean; serial_number: string; has_comm_key: boolean;
  punch_count?: number; user_count?: number; first_punch?: string | null; last_punch?: string | null;
};
type SyncRun = { id: number; status: string; message: string; error_message: string; records_fetched: number; records_inserted: number; records_skipped: number };
type Punch = { id: number; device_user_id: string; punched_at: string; punch: number; status_code: number };
type MapRow = { device_user_id: string; name_on_device: string; employee_id: string; employee_name: string; mapped: boolean };
type Person = { employee_id: string; full_name: string };

export function DevicePage({ role = "viewer" }: { role?: string }) {
  const { deviceId = "" } = useParams();
  const navigate = useNavigate();
  const [device, setDevice] = useState<Device | null>(null);
  const [punches, setPunches] = useState<Punch[]>([]);
  const [users, setUsers] = useState<MapRow[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const generation = useRef(0);
  const canWrite = role === "admin" || role === "supervisor";

  function load() {
    api<Device>(`/api/v1/devices/${deviceId}`).then(setDevice).catch((err) => setError(err.message));
    api<{ items: Punch[] }>(`/api/v1/devices/${deviceId}/punches`).then((body) => setPunches(body.items)).catch(() => setPunches([]));
    api<{ items: MapRow[] }>(`/api/v1/devices/${deviceId}/users`).then((body) => setUsers(body.items)).catch(() => setUsers([]));
  }
  useEffect(() => {
    load();
    return () => {
      generation.current += 1;
    };
  }, [deviceId]);

  async function act(path: string, body?: unknown) {
    setError("");
    setNotice("");
    try {
      const result = await api<Record<string, unknown>>(`/api/v1/devices/${deviceId}/${path}`, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      const run = result.run as { status?: string; error_message?: string; message?: string } | undefined;
      if (run?.status === "error") setError(run.error_message || run.message || "Sync failed");
      else if (result.ok === false && typeof result.message === "string") setError(result.message);
      else if (typeof result.warning === "string") setNotice(result.warning);
      else if (typeof result.message === "string") setNotice(result.message);
      else if (run?.message) setNotice(run.message);
      else setNotice("Done.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }

  useEffect(() => {
    const term = search.trim();
    if (term.length < 2) {
      setPeople([]);
      return undefined;
    }
    const timer = window.setTimeout(() => {
      api<{ items: Person[] }>(`/api/v1/employees${qs({ q: term, page_size: 20 })}`)
        .then((body) => setPeople(body.items))
        .catch(() => setPeople([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  async function syncNow() {
    const token = generation.current;
    const id = deviceId;
    setError("");
    setNotice("");
    setBusy("Connecting to the terminal and downloading its log…");
    try {
      const started = await api<{ run: { id: number } }>(`/api/v1/devices/${id}/sync`, { method: "POST" });
      const runId = started.run.id;
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        if (generation.current !== token) return;
        const run = await api<SyncRun>(`/api/v1/sync-runs/${runId}`);
        if (generation.current !== token) return;
        const progress = run.records_fetched
          ? `Downloaded ${run.records_fetched}. Saved ${run.records_inserted}, already stored ${run.records_skipped}.`
          : run.message || run.status;
        setBusy(progress);
        if (run.status === "success" || run.status === "partial") {
          setNotice(run.message || "Sync finished.");
          setBusy("");
          load();
          return;
        }
        if (run.status === "error") {
          setError(run.error_message || run.message || "Sync failed");
          setBusy("");
          load();
          return;
        }
      }
      if (generation.current !== token) return;
      setError("The download is still running. Refresh this page in a minute.");
      setBusy("");
    } catch (err) {
      if (generation.current !== token) return;
      setBusy("");
      setError(err instanceof Error ? err.message : "Sync failed");
    }
  }

  function exportDevice() {
    const end = (device?.last_punch || "").slice(0, 10);
    if (!end) {
      setError("This device has no imported punches to export yet.");
      return;
    }
    const start = `${end.slice(0, 8)}01`;
    setError("");
    download(`/api/v1/exports${qs({ report: "monthly", format: "xlsx", source: "device", device_id: deviceId, start_date: start, end_date: end })}`).catch((err) => setError(err.message));
  }

  async function sample() {
    const day = new Date();
    const stamp = (hours: number) => {
      const value = new Date(day.getFullYear(), day.getMonth(), day.getDate(), hours, 0, 0);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:00:00`;
    };
    await act("simulator-logs", {
      users: [{ user_id: "1001", name: "Sample user" }],
      logs: [
        { user_id: "1001", punched_at: stamp(8), punch: 0, status: 0, uid: 1 },
        { user_id: "1001", punched_at: stamp(17), punch: 1, status: 1, uid: 2 },
      ],
    });
    await act("sync?wait=1");
  }

  async function mapUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await act("map", { device_user_id: form.get("device_user_id"), employee_id: form.get("employee_id") || null });
  }

  if (!device && !error) return <p>Loading…</p>;
  if (!device) return <p className="error">{error}</p>;
  return (
    <>
      <div className="top">
        <div>
          <h1>{device.name}</h1>
          <p className="lede">{device.host}:{device.port} · {device.protocol} · {device.model || "model not set"} · {device.branch || "No branch"}</p>
        </div>
        <span className={`badge ${device.connection_status}`}>{device.connection_status}</span>
      </div>
      {device.simulated ? <p className="banner">This adapter is a labeled simulator. A successful test here is not proof that a physical ZKTeco terminal works.</p> : null}
      {device.last_error ? <p className="error">{device.last_error}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <section className="cards">
        <article className="card feature"><div className="k">Punches stored</div><div className="s">{device.punch_count ?? 0}</div></article>
        <article className="card"><div className="k">People from this terminal</div><div className="s">{device.user_count ?? 0}</div></article>
        <article className="card"><div className="k">Attendance dates</div><div className="s">{device.first_punch ? `${device.first_punch.slice(0, 10)} → ${device.last_punch?.slice(0, 10)}` : "None imported"}</div></article>
        <article className="card"><div className="k">Last sync</div><div className="s">{device.last_sync_at || "Never"} · {device.last_sync_status || "—"}</div></article>
      </section>
      {busy ? <p className="banner">{busy}</p> : null}
      {canWrite ? (
        <div className="row-actions" style={{ margin: "14px 0" }}>
          <button className="btn" type="button" disabled={!!busy} onClick={() => act("test")}>Test connection</button>
          <button className="btn" type="button" disabled={!!busy} onClick={syncNow}>Sync now</button>
          <button className="btn ghost" type="button" disabled={!!busy} onClick={exportDevice}>{device.last_punch ? `Export ${device.last_punch.slice(0, 7)}` : "Export this device"}</button>
          {device.simulated ? <button className="btn ghost" type="button" disabled={!!busy} onClick={sample}>Load labeled sample punches</button> : null}
          <button className="btn ghost" type="button" disabled={!!busy} onClick={async () => {
            if (!window.confirm("Delete this device and remove its imported attendance from reports? The terminal itself is not cleared.")) return;
            try {
              await api(`/api/v1/devices/${deviceId}`, { method: "DELETE" });
              navigate("/devices");
            } catch (err) {
              setError(err instanceof Error ? err.message : "Could not delete");
            }
          }}>Delete device</button>
        </div>
      ) : null}
      <div className="grid-2">
        <section className="panel">
          <h2>Latest punches</h2>
          <p className="lede">Newest {punches.length} of {device.punch_count ?? punches.length} stored punches. Export {device.last_punch ? device.last_punch.slice(0, 7) : "the latest month"} uses the punches on the terminal, not the current calendar month.</p>
          <table>
            <thead><tr><th>User</th><th>Time</th><th>Punch</th><th>Status</th></tr></thead>
            <tbody>{punches.map((row) => <tr key={row.id}><td>{row.device_user_id}</td><td>{row.punched_at}</td><td>{row.punch}</td><td>{row.status_code}</td></tr>)}</tbody>
          </table>
          {!punches.length ? <p className="empty">No punches imported yet.</p> : null}
        </section>
        <section className="panel">
          <h2>People copied from this terminal</h2>
          <p className="lede">{users.length} user ids. Sync creates these employees from the machine. You do not type them in.</p>
          <table>
            <thead><tr><th>Device user</th><th>Employee</th></tr></thead>
            <tbody>{users.slice(0, 40).map((row) => <tr key={row.device_user_id}><td>{row.device_user_id} {row.name_on_device}</td><td>{row.mapped ? `${row.employee_id} ${row.employee_name}` : "Unmapped"}</td></tr>)}</tbody>
          </table>
          {users.length > 40 ? <p className="lede">{users.length - 40} more people are stored and included in the export.</p> : null}
          {canWrite ? (
            <form className="stack" style={{ marginTop: 12 }} onSubmit={mapUser}>
              <label className="field">Device user ID<input name="device_user_id" required /></label>
              <label className="field">Employee ID or name
                <input
                  name="employee_id"
                  list="employee-options"
                  autoComplete="off"
                  placeholder="Type two letters or digits. Leave empty to unlink."
                  onChange={(event) => setSearch(event.target.value)}
                />
                <datalist id="employee-options">
                  {people.map((row) => <option key={row.employee_id} value={row.employee_id}>{row.full_name}</option>)}
                </datalist>
              </label>
              <button className="btn" type="submit">Save mapping</button>
            </form>
          ) : null}
        </section>
      </div>
    </>
  );
}
