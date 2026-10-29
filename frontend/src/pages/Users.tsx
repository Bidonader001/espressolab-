import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";

type Account = { id: number; username: string; role: string; is_active: boolean };

export function UsersPage() {
  const [items, setItems] = useState<Account[]>([]);
  const [error, setError] = useState("");

  function load() {
    api<{ items: Account[] }>("/api/v1/users").then((body) => setItems(body.items)).catch((err) => setError(err.message));
  }
  useEffect(() => { load(); }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    try {
      await api("/api/v1/users", {
        method: "POST",
        body: JSON.stringify({ username: data.get("username"), password: data.get("password"), role: data.get("role") }),
      });
      form.reset();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <>
      <div className="top"><div><h1>Permissions</h1><p className="lede">Viewers can read. Supervisors can maintain attendance data. Administrators manage users and settings.</p></div></div>
      {error ? <p className="error">{error}</p> : null}
      <section className="panel">
        <table>
          <thead><tr><th>Username</th><th>Role</th><th>Active</th></tr></thead>
          <tbody>{items.map((row) => <tr key={row.id}><td>{row.username}</td><td>{row.role}</td><td>{row.is_active ? "Yes" : "No"}</td></tr>)}</tbody>
        </table>
      </section>
      <form className="panel form-grid" style={{ marginTop: 14 }} onSubmit={create}>
        <label className="field">Username<input name="username" required minLength={2} /></label>
        <label className="field">Password<input name="password" type="password" required minLength={8} /></label>
        <label className="field">Role
          <select name="role" defaultValue="viewer"><option>viewer</option><option>supervisor</option><option>admin</option></select>
        </label>
        <button className="btn" type="submit">Create user</button>
      </form>
    </>
  );
}
