import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, qs } from "../api";

type Employee = {
  employee_id: string;
  full_name: string;
  email: string;
  phone: string;
  job_title: string;
  department: string;
  branch_id: number | null;
  shift_id: number | null;
  employment_status: string;
  joining_date: string;
  manager: string;
};
type History = { date: string; check_in: string; check_out: string; hours: number | null; hours_text?: string; status: string; late_minutes: number };

export function EmployeeDetailPage() {
  const { employeeId = "" } = useParams();
  const [person, setPerson] = useState<Employee | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [branches, setBranches] = useState<{ id: number; name: string }[]>([]);
  const [shifts, setShifts] = useState<{ id: number; name: string }[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function load() {
    api<Employee>(`/api/v1/employees/${encodeURIComponent(employeeId)}`).then(setPerson).catch((err) => setError(err.message));
    const end = new Date().toISOString().slice(0, 10);
    const start = new Date(Date.now() - 1000 * 60 * 60 * 24 * 30).toISOString().slice(0, 10);
    api<{ details: History[] }>(`/api/v1/employees/${encodeURIComponent(employeeId)}/attendance${qs({ start_date: start, end_date: end })}`)
      .then((body) => setHistory(body.details))
      .catch((err) => setError(err.message));
  }
  useEffect(() => {
    load();
    api<{ items: { id: number; name: string }[] }>("/api/v1/branches").then((body) => setBranches(body.items));
    api<{ items: { id: number; name: string }[] }>("/api/v1/shifts").then((body) => setShifts(body.items));
  }, [employeeId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!person) return;
    const form = new FormData(event.currentTarget);
    try {
      const saved = await api<Employee>(`/api/v1/employees/${encodeURIComponent(person.employee_id)}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...person,
          full_name: form.get("full_name"),
          email: form.get("email"),
          phone: form.get("phone"),
          job_title: form.get("job_title"),
          department: form.get("department"),
          manager: form.get("manager"),
          joining_date: form.get("joining_date"),
          branch_id: Number(form.get("branch_id")) || null,
          shift_id: Number(form.get("shift_id")) || null,
          employment_status: form.get("employment_status"),
        }),
      });
      setPerson(saved);
      setMessage("Saved. If the shift changed, sessions were recalculated from the original punches.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function deactivate() {
    if (!person || !confirm("Deactivate this employee? Attendance history stays.")) return;
    try {
      const result = await api<{ detail?: string }>(`/api/v1/employees/${encodeURIComponent(person.employee_id)}`, { method: "DELETE" });
      setMessage(result.detail || "Removed.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update");
    }
  }

  if (!person) return error ? <p className="error">{error}</p> : <p>Loading…</p>;
  return (
    <>
      <div className="top"><div><h1>{person.full_name}</h1><p className="lede">{person.employee_id}</p></div></div>
      {error ? <p className="error">{error}</p> : null}
      {message ? <div className="banner">{message}</div> : null}
      <form className="panel form-grid" onSubmit={save}>
        <label className="field">Full name<input name="full_name" defaultValue={person.full_name} required /></label>
        <label className="field">Email<input name="email" defaultValue={person.email} /></label>
        <label className="field">Phone<input name="phone" defaultValue={person.phone} /></label>
        <label className="field">Job title<input name="job_title" defaultValue={person.job_title} /></label>
        <label className="field">Department<input name="department" defaultValue={person.department} /></label>
        <label className="field">Manager<input name="manager" defaultValue={person.manager} /></label>
        <label className="field">Branch
          <select name="branch_id" defaultValue={person.branch_id || ""}>{branches.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
        </label>
        <label className="field">Shift
          <select name="shift_id" defaultValue={person.shift_id || ""}>
            <option value="">Unassigned</option>
            {shifts.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select>
        </label>
        <label className="field">Status
          <select name="employment_status" defaultValue={person.employment_status}><option value="active">active</option><option value="inactive">inactive</option></select>
        </label>
        <label className="field">Joining date<input name="joining_date" type="date" defaultValue={person.joining_date} /></label>
        <div className="row-actions"><button className="btn" type="submit">Save</button><button className="btn ghost" type="button" onClick={deactivate}>Deactivate</button></div>
      </form>
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Last 30 days</h2>
        {history.length === 0 ? <p className="empty">No calculated attendance in this window.</p> : (
          <table>
            <thead><tr><th>Date</th><th>In</th><th>Out</th><th>Hours</th><th>Status</th></tr></thead>
            <tbody>
              {history.map((row) => (
                <tr key={row.date} className={`row-${row.status.toLowerCase().replace(" ", "")}`}><td>{row.date}</td><td>{row.check_in || "—"}</td><td>{row.status === "Incomplete" ? <span className="no-checkout">No check-out</span> : row.check_out || "—"}</td><td>{row.hours_text || "—"}</td><td><span className={`badge ${row.status.toLowerCase().replace(" ", "")}`}>{row.status}</span></td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
