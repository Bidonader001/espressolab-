import { useEffect, useState } from "react";
import { api } from "../api";

type Row = { id: number; created_at: string; actor: string; action: string; entity: string; entity_id: string; detail: string };

export function AuditPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ items: Row[] }>("/api/v1/audit").then((body) => setItems(body.items)).catch((err) => setError(err.message));
  }, []);
  return (
    <>
      <div className="top"><div><h1>Audit log</h1><p className="lede">Sign-ins, device tests, mappings, and setting changes.</p></div></div>
      {error ? <p className="error">{error}</p> : null}
      <section className="panel">
        <table>
          <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Record</th><th>Detail</th></tr></thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}><td>{row.created_at}</td><td>{row.actor}</td><td>{row.action}</td><td>{row.entity} {row.entity_id}</td><td>{row.detail}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
