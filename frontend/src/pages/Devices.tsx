import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

type Device = { id: number; name: string; host: string; port: number; protocol: string; connection_status: string; last_sync_at: string | null; branch: string; simulated: boolean };
type Branch = { id: number; name: string };
type SyncRun = { id: number; status: string; message: string; error_message: string; device_name: string };

const DONE = new Set(["success", "partial", "error"]);

function unsyncedMessage(items: Device[]): string {
  if (!items.length) return "No machines are registered.";
  const pending = items.filter((row) => !row.last_sync_at);
  if (!pending.length) return "";
  if (pending.length === items.length) return "No machine has been synced yet.";
  return `Not synced yet: ${pending.map((row) => row.name).join(", ")}.`;
}

export function DevicesPage({ role = "viewer" }: { role?: string }) {
  const navigate = useNavigate();
  const [items, setItems] = useState<Device[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [ready, setReady] = useState(false);
  const canWrite = role === "admin" || role === "supervisor";

  function load() {
    api<{ items: Device[] }>("/api/v1/devices")
      .then((body) => {
        setItems(body.items);
        setReady(true);
      })
      .catch((err) => setError(err.message));
  }
  useEffect(() => {
    load();
    api<{ items: Branch[] }>("/api/v1/branches").then((body) => setBranches(body.items));
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    try {
      await api("/api/v1/devices", {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name"),
          host: data.get("host"),
          port: Number(data.get("port") || 4370),
          model: data.get("model"),
          protocol: data.get("protocol"),
          branch_id: Number(data.get("branch_id")) || null,
          timeout_seconds: Number(data.get("timeout_seconds") || 8),
          sync_enabled: false,
          serial_number: data.get("serial_number"),
          comm_key: data.get("comm_key") || null,
        }),
      });
      form.reset();
      setNotice("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Delete this device and remove its imported attendance from reports? The terminal itself is not cleared.")) return;
    setError("");
    try {
      await api(`/api/v1/devices/${id}`, { method: "DELETE" });
      setNotice("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete");
    }
  }

  async function syncAll() {
    setError("");
    setNotice("");
    setSyncing(true);
    try {
      const started = await api<{ runs: number[]; message?: string }>("/api/v1/devices/sync-all", { method: "POST" });
      if (!started.runs.length) {
        setNotice(started.message || "No machine has been synced.");
        return;
      }
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        const runs = await Promise.all(started.runs.map((id) => api<SyncRun>(`/api/v1/sync-runs/${id}`)));
        const finished = runs.filter((run) => DONE.has(run.status));
        setNotice(`Syncing ${finished.length} of ${runs.length}…`);
        if (finished.length !== runs.length) continue;
        const failed = runs.filter((run) => run.status === "error");
        load();
        if (failed.length) {
          setNotice("");
          setError(failed.map((run) => `${run.device_name || "Terminal"}: ${run.error_message || run.message || "Sync failed"}`).join(" "));
        } else {
          setNotice("Sync finished.");
        }
        return;
      }
      setNotice("");
      setError("Sync is still running. Check the machines again in a minute.");
    } catch (err) {
      setNotice("");
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  const standing = !ready || syncing ? "" : unsyncedMessage(items);
  const warning = notice && notice !== "Sync finished." ? "" : standing;

  return (
    <>
      <div className="top">
        <div><h1>ZKTeco devices</h1><p className="lede">The server reads logs from each machine. It never clears the terminal.</p></div>
        {canWrite ? <button className="btn" type="button" disabled={syncing} onClick={syncAll}>{syncing ? "Syncing…" : "Sync all"}</button> : null}
      </div>
      {warning ? <p className="banner">{warning}</p> : null}
      {notice ? <p className="banner">{notice}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <section className="panel">
        <table>
          <thead><tr><th>Name</th><th>Host</th><th>Protocol</th><th>Branch</th><th>Status</th><th>Last sync</th><th></th></tr></thead>
          <tbody>
            {items.map((row) => (
              <tr className="click" key={row.id} onClick={() => navigate(`/devices/${row.id}`)}>
                <td>{row.name}</td>
                <td>{row.host}:{row.port}</td>
                <td>{row.simulated ? <span className="badge simulated">simulator</span> : row.protocol}</td>
                <td>{row.branch || "—"}</td>
                <td><span className={`badge ${row.connection_status}`}>{row.connection_status}</span></td>
                <td>{row.last_sync_at || "—"}</td>
                <td>{canWrite ? <button className="btn ghost" type="button" onClick={(event) => { event.stopPropagation(); remove(row.id); }}>Delete</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {canWrite ? (
        <form className="panel form-grid" style={{ marginTop: 14 }} onSubmit={create}>
          <h2 style={{ gridColumn: "1 / -1" }}>Register a device</h2>
          <label className="field">Name<input name="name" required /></label>
          <label className="field">IP or hostname<input name="host" required placeholder="192.168.1.201" /></label>
          <label className="field">Port<input name="port" type="number" defaultValue={4370} /></label>
          <label className="field">Model<input name="model" placeholder="K40 / SpeedFace / …" /></label>
          <label className="field">Protocol
            <select name="protocol" defaultValue="tcp">
              <option value="tcp">pyzk TCP</option>
              <option value="udp">pyzk UDP</option>
              <option value="push">ADMS push</option>
              <option value="agent">Branch agent</option>
              <option value="simulator">Simulator (not hardware)</option>
            </select>
          </label>
          <label className="field">Branch
            <select name="branch_id"><option value="">None</option>{branches.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
          </label>
          <label className="field">Timeout seconds<input name="timeout_seconds" type="number" defaultValue={8} /></label>
          <label className="field">Comm key<input name="comm_key" inputMode="numeric" /></label>
          <label className="field">Serial (push)<input name="serial_number" /></label>
          <button className="btn" type="submit">Add device</button>
        </form>
      ) : null}
    </>
  );
}
