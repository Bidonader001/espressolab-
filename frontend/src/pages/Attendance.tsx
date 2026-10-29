import { FormEvent, useEffect, useState } from "react";
import { api, qs } from "../api";

type Row = {
  employee_id: string;
  name: string;
  date: string;
  check_in: string;
  check_out: string;
  hours: number | null;
  hours_text?: string;
  status: string;
  branch: string;
  department: string;
  shift: string;
};

export function AttendancePage() {
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [totals, setTotals] = useState({ hours: "0:00", incomplete: 0 });
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ start_date: "", end_date: "", branch: "", department: "", status: "", q: "", source: "device" });

  function load(next = page, current = filters) {
    setError("");
    const query = qs({ ...current, page: next, page_size: 50 });
    // One request: the report itself now lists Absent, Weekend and On Leave days next to worked days.
    api<{ items: Row[]; total: number; summary: { total_minutes: number; incomplete_days: number }[] }>(`/api/v1/attendance${query}`)
      .then((body) => {
        setItems(body.items);
        const minutes = body.summary.reduce((sum, person) => sum + person.total_minutes, 0);
        setTotals({
          hours: `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`,
          incomplete: body.summary.reduce((sum, person) => sum + person.incomplete_days, 0),
        });
        setTotal(body.total);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    load(1);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    load(1);
  }

  return (
    <>
      <div className="top"><div><h1>Attendance</h1><p className="lede">{total} rows for people read from the attendance machines. Total hours {totals.hours} (hours:minutes, check-out minus check-in). {totals.incomplete} incomplete days have no check-out and no hours.</p></div></div>
      <form className="filters" onSubmit={submit}>
        <label className="field">From<input type="date" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} /></label>
        <label className="field">To<input type="date" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} /></label>
        <label className="field">Branch<input value={filters.branch} onChange={(e) => setFilters({ ...filters, branch: e.target.value })} /></label>
        <label className="field">Department<input value={filters.department} onChange={(e) => setFilters({ ...filters, department: e.target.value })} /></label>
        <label className="field">Status
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">All</option>
            {["Present", "Late", "Absent", "Incomplete", "On Leave", "Weekend"].map((status) => <option key={status}>{status}</option>)}
          </select>
        </label>
        <label className="field">Search<input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} /></label>
        <button className="btn" type="submit">Apply</button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      <section className="panel" style={{ marginTop: 14 }}>
        <table>
          <thead>
            <tr><th>Employee ID</th><th>Name</th><th>Date</th><th>Check-in</th><th>Check-out</th><th>Hours</th><th>Status</th><th>Branch</th></tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={`${row.employee_id}-${row.date}-${row.status}`} className={`row-${row.status.toLowerCase().replace(" ", "")}`}>
                <td>{row.employee_id}</td>
                <td>{row.name}</td>
                <td>{row.date}</td>
                <td>{row.check_in || "—"}</td>
                <td>{row.status === "Incomplete" ? <span className="no-checkout">No check-out</span> : row.check_out || "—"}</td>
                <td>{row.hours_text || "—"}</td>
                <td><span className={`badge ${row.status.toLowerCase().replace(" ", "")}`}>{row.status}</span></td>
                <td>{row.branch}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length ? <p className="empty">No attendance rows for this filter.</p> : null}
        <div className="pager">
          <button className="btn ghost" type="button" disabled={page <= 1} onClick={() => { setPage(page - 1); load(page - 1); }}>Previous</button>
          <span>Page {page}</span>
          <button className="btn ghost" type="button" disabled={page * 50 >= total} onClick={() => { setPage(page + 1); load(page + 1); }}>Next</button>
        </div>
      </section>
    </>
  );
}
