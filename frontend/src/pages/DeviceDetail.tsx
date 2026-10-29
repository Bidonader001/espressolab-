import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

type Device = {
  id: number;
  name: string;
  host: string;
  port: number;
  protocol: string;
  model: string;
  firmware: string;
  serial_number: string;
  connection_status: string;
  last_error: string;
  last_sync_at: string | null;
  last_test_at: string | null;
  timeout_seconds: number;
  sync_interval_minutes: number;
  sync_enabled: boolean;
  simulated: boolean;
  has_comm_key: boolean;
};
type Punch = { id: number; device_user_id: string; punched_at: string; punch: number; status_code: number };
type DeviceUser = { device_user_id: string; name_on_device: string; employee_id: string; employee_name: string; mapped: boolean };
type Run = { id: number; status: string; message: string; error_message: string; records_inserted: number; records_skipped: number };
type Employee = { employee_id: string; full_name: string };

export function DeviceDetailPage({ role }: { role: string }) {
  const canWrite = role !== "viewer";
  const { deviceId = "" } = useParams();
  const [device, setDevice] = useState<Device | null>(null);
  const [punches, setPunches] = useState<Punch[]>([]);
  const [users, setUsers] = useState<DeviceUser[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  function load() {
    api<Device>(`/api/v1/devices/${deviceId}`).then(setDevice).catch((err) => setError(err.message));
    api<{ items: Punch[] }>(`/api/v1/devices/${deviceId}/punches`).then((body) => setPunches(body.items));
    api<{ items: DeviceUser[] }>(`/api/v1/devices/${deviceId}/users`).then((body) => setUsers(body.items));
  }
  useEffect(() => {
    load();
    api<{ items: Employee[] }>("/api/v1/employees?page_size=200").then((body) => setEmployees(body.items));
  }, [deviceId]);

  useEffect(() => {
    if (!run || ["success", "error", "partial"].includes(run.status)) return;
    const timer = window.setInterval(async () => {
      const next = await api<Run>(`/api/v1/sync-runs/${run.id}`);
      setRun(next);
      if (["success", "error", "partial"].includes(next.status)) {
        load();
        window.clearInterval(timer);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [run?.id, run?.status]);

  async function test() {
    setBusy("test");
    setError("");
    try {
      const result = await api<{ message: string; ok: boolean; simulated: boolean; device: Device }>(`/api/v1/devices/${deviceId}/test`, { method: "POST" });
      setDevice(result.device);
      setMessage(result.simulated ? result.message : result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy("");
    }
  }

  async function sync() {
    setBusy("sync");
    setError("");
    try {
      const result = await api<{ run: Run }>(`/api/v1/devices/${deviceId}/sync`, { method: "POST" });
      setRun(result.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setBusy("");
    }
  }

  async function mapUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api(`/api/v1/devices/${deviceId}/map`, {
        method: "POST",
        body: JSON.stringify({ device_user_id: form.get("device_user_id"), employee_id: form.get("employee_id") || null }),
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mapping failed");
    }
  }

  async function storeSimulator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const payload = JSON.parse(String(form.get("fixture") || "{\"logs\":[]}"));
      const result = await api<{ warning: string }>(`/api/v1/devices/${deviceId}/simulator-logs`, { method: "POST", body: JSON.stringify(payload) });
      setMessage(result.warning + " Run Sync to import them.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The fixture was not stored");
    }
  }

  if (!device) return error ? <p className="error">{error}</p> : <p>Loading…</p>;
  return (
    <>
      <div className="top">
        <div>
          <h1>{device.name}</h1>
          <p className="lede">{device.host}:{device.port} · {device.protocol}{device.model ? ` · ${device.model}` : ""}{device.firmware ? ` · firmware ${device.firmware}` : ""}</p>
        </div>
        {canWrite ? (
          <div className="row-actions">
            <button className="btn ghost" type="button" disabled={busy === "test"} onClick={test}>{busy === "test" ? "Testing…" : "Test connection"}</button>
            <button className="btn" type="button" disabled={busy === "sync"} onClick={sync}>{busy === "sync" ? "Starting…" : "Sync now"}</button>
          </div>
        ) : null}
      </div>
      {device.simulated ? <div className="banner">Simulated adapter. These results are not from a ZKTeco machine.</div> : null}
      {device.protocol === "agent" ? <div className="banner">This terminal is read by the branch agent on the store LAN. The application server does not open a connection to {device.host}.</div> : null}
      {device.protocol === "push" ? <div className="banner">Point the terminal at /iclock/cdata on this server and set its serial to {device.serial_number || "(missing)"}.</div> : null}
      {error ? <p className="error">{error}</p> : null}
      {message ? <div className="banner">{message}</div> : null}
      <div className="cards">
        <article className="card"><div className="k">Connection</div><div className="v" style={{ fontSize: 28 }}><span className={`badge ${device.connection_status}`}>{device.connection_status}</span></div></article>
        <article className="card"><div className="k">Last test</div><div className="s">{device.last_test_at || "Never"}</div><div className="s">{device.last_error || "No error stored."}</div></article>
        <article className="card"><div className="k">Last sync</div><div className="s">{device.last_sync_at || "Never"}</div><div className="s">Every {device.sync_interval_minutes} min · timeout {device.timeout_seconds}s · key {device.has_comm_key ? "set" : "none"}</div></article>
        <article className="card"><div className="k">Serial</div><div className="s">{device.serial_number || "—"}</div></article>
      </div>
      {run ? <section className="panel" style={{ marginTop: 14 }}><h2>Sync progress</h2><p><span className={`badge ${run.status}`}>{run.status}</span> {run.message}</p>{run.error_message ? <p className="error">{run.error_message}</p> : null}<p>Inserted {run.records_inserted}, duplicates skipped {run.records_skipped}.</p></section> : null}
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Device users</h2>
        <p className="lede">Map each terminal user ID to an employee. Unmapped punches stay stored and stay out of the reports.</p>
        {users.length === 0 ? <p className="empty">No users seen yet. Sync the terminal first.</p> : (
          <table>
            <thead><tr><th>Device user</th><th>Name on device</th><th>Employee</th><th></th></tr></thead>
            <tbody>
              {users.map((row) => (
                <tr key={row.device_user_id}>
                  <td>{row.device_user_id}</td>
                  <td>{row.name_on_device || "—"}</td>
                  <td>{row.mapped ? `${row.employee_name} (${row.employee_id})` : "Unmapped"}</td>
                  <td>
                    {canWrite ? (
                      <form onSubmit={mapUser} className="row-actions">
                        <input type="hidden" name="device_user_id" value={row.device_user_id} />
                        <select name="employee_id" defaultValue={row.employee_id}>
                          <option value="">Unmapped</option>
                          {employees.map((person) => <option key={person.employee_id} value={person.employee_id}>{person.full_name}</option>)}
                        </select>
                        <button className="btn ghost" type="submit">Map</button>
                      </form>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Latest imported punches</h2>
        {punches.length === 0 ? <p className="empty">No punches imported from this device.</p> : (
          <table>
            <thead><tr><th>When</th><th>Device user</th><th>Punch</th><th>Status code</th></tr></thead>
            <tbody>{punches.map((row) => <tr key={row.id}><td>{row.punched_at}</td><td>{row.device_user_id}</td><td>{row.punch}</td><td>{row.status_code}</td></tr>)}</tbody>
          </table>
        )}
      </section>
      {device.simulated && canWrite ? (
        <form className="panel" style={{ marginTop: 14 }} onSubmit={storeSimulator}>
          <h2>Simulator fixture</h2>
          <p className="lede">Development only. Paste logs, then sync. This does not talk to hardware.</p>
          <textarea name="fixture" defaultValue={'{\n  "logs": [\n    {"user_id": "1", "punched_at": "2026-10-27T08:55:00", "punch": 0}\n  ],\n  "users": [{"user_id": "1", "name": "Sample"}]\n}'} />
          <div style={{ marginTop: 8 }}><button className="btn" type="submit">Store fixture</button></div>
        </form>
      ) : null}
    </>
  );
}
