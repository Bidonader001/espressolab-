import { useEffect, useState } from "react";
import { api } from "../api";

type Run = {
  id: number; device_name: string; trigger: string; status: string; message: string;
  started_at: string | null; finished_at: string | null; records_fetched: number; records_inserted: number;
  records_skipped: number; error_message: string;
};

export function SyncPage() {
  const [items, setItems] = useState<Run[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ items: Run[] }>("/api/v1/sync-runs").then((body) => setItems(body.items)).catch((err) => setError(err.message));
  }, []);
  return (
    <>
      <div className="top"><div><h1>Synchronization history</h1><p className="lede">Every attempt is kept, including timeouts and rejected serial numbers.</p></div></div>
      {error ? <p className="error">{error}</p> : null}
      <section className="panel">
        <table>
          <thead><tr><th>When</th><th>Device</th><th>Trigger</th><th>Status</th><th>Fetched</th><th>New</th><th>Skipped</th><th>Error</th></tr></thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.finished_at || row.started_at}</td>
                <td>{row.device_name}</td>
                <td>{row.trigger}</td>
                <td><span className={`badge ${row.status}`}>{row.status}</span></td>
                <td>{row.records_fetched}</td>
                <td>{row.records_inserted}</td>
                <td>{row.records_skipped}</td>
                <td>{row.error_message}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length ? <p className="empty">No synchronization attempts yet.</p> : null}
      </section>
    </>
  );
}
