import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, qs } from "../api";

type Person = { employee_id: string; full_name: string; department: string; job_title: string; branch: string; shift: string; employment_status: string };
type Branch = { id: number; name: string };
type Shift = { id: number; name: string };

const PAGE_SIZE = 100;

export function EmployeesPage({ role = "viewer" }: { role?: string }) {
  const navigate = useNavigate();
  const canWrite = role === "admin" || role === "supervisor";
  const [items, setItems] = useState<Person[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [busy, setBusy] = useState(false);

  function load(next = page, query = q, state = status) {
    api<{ items: Person[]; total: number }>(`/api/v1/employees${qs({ q: query, status: state, page: next, page_size: PAGE_SIZE })}`)
      .then((body) => {
        setItems(body.items);
        setTotal(body.total);
      })
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    load(1, "", "");
    api<{ items: Branch[] }>("/api/v1/branches").then((body) => setBranches(body.items));
    api<{ items: Shift[] }>("/api/v1/shifts").then((body) => setShifts(body.items));
  }, []);

  function clearSelection() {
    setSelected(new Set());
    setAllMatching(false);
  }

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    clearSelection();
    setNotice("");
    load(1);
  }

  function go(next: number) {
    setPage(next);
    load(next);
  }

  const pageIds = items.map((row) => row.employee_id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const count = allMatching ? total : selected.size;

  function toggleOne(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
    setAllMatching(false);
  }

  function togglePage() {
    const next = new Set(selected);
    if (allOnPage) pageIds.forEach((id) => next.delete(id));
    else pageIds.forEach((id) => next.add(id));
    setSelected(next);
    setAllMatching(false);
  }

  async function applyStatus(target: "active" | "inactive") {
    if (!count) return;
    const word = target === "active" ? "active" : "inactive";
    const text = `Make ${count} employee${count === 1 ? "" : "s"} ${word}? ${target === "inactive" ? "They leave the reports, but their attendance history is kept." : "They appear in the reports again."}`;
    if (!window.confirm(text)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const body = allMatching
        ? { status: target, match: { q, status } }
        : { status: target, employee_ids: Array.from(selected) };
      const done = await api<{ selected: number; changed: number }>("/api/v1/employees/bulk-status", { method: "POST", body: JSON.stringify(body) });
      setNotice(`${done.changed} employee${done.changed === 1 ? "" : "s"} set to ${word}${done.selected !== done.changed ? ` (${done.selected - done.changed} already were)` : ""}.`);
      clearSelection();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update");
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    try {
      await api("/api/v1/employees", {
        method: "POST",
        body: JSON.stringify({
          employee_id: data.get("employee_id"),
          full_name: data.get("full_name"),
          department: data.get("department"),
          job_title: data.get("job_title"),
          branch_id: Number(data.get("branch_id")) || null,
          shift_id: Number(data.get("shift_id")) || null,
          employment_status: "active",
        }),
      });
      form.reset();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <div className="top"><div><h1>Employees</h1><p className="lede">Synchronizing a terminal adds its users here. Tick employees to make them active or inactive. Inactive people are left out of reports, and their attendance history is kept. A typed-in record is not included in the machine export until that person is linked to a device user.</p></div></div>
      <form className="filters" onSubmit={search}>
        <label className="field wide">Search<input value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <label className="field">Status
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); clearSelection(); load(1, q, e.target.value); }}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <button className="btn" type="submit">Search</button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      {canWrite && count > 0 ? (
        <div className="bulkbar">
          <strong>{count} selected</strong>
          <button className="btn" type="button" disabled={busy} onClick={() => applyStatus("active")}>Make active</button>
          <button className="btn ghost" type="button" disabled={busy} onClick={() => applyStatus("inactive")}>Make inactive</button>
          <button className="btn ghost" type="button" disabled={busy} onClick={clearSelection}>Clear</button>
        </div>
      ) : null}
      {canWrite && allOnPage && !allMatching && total > items.length ? (
        <p className="notice">All {items.length} on this page are selected. <button className="linkish" type="button" onClick={() => setAllMatching(true)}>Select all {total} that match</button></p>
      ) : null}
      {allMatching ? <p className="notice">All {total} employees that match this search are selected. <button className="linkish" type="button" onClick={clearSelection}>Clear selection</button></p> : null}
      <section className="panel" style={{ marginTop: 14 }}>
        <table>
          <thead>
            <tr>
              {canWrite ? <th style={{ width: 32 }}><input type="checkbox" aria-label="Select all on this page" checked={allOnPage} onChange={togglePage} /></th> : null}
              <th>ID</th><th>Name</th><th>Department</th><th>Title</th><th>Branch</th><th>Shift</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr className="click" key={row.employee_id} onClick={() => navigate(`/employees/${encodeURIComponent(row.employee_id)}`)}>
                {canWrite ? (
                  <td onClick={(event) => event.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${row.full_name}`} checked={allMatching || selected.has(row.employee_id)} onChange={() => toggleOne(row.employee_id)} />
                  </td>
                ) : null}
                <td>{row.employee_id}</td><td>{row.full_name}</td><td>{row.department}</td><td>{row.job_title}</td><td>{row.branch}</td><td>{row.shift}</td>
                <td><span className={`badge ${row.employment_status}`}>{row.employment_status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length ? <p className="empty">No employees match.</p> : null}
        <div className="pager">
          <button className="btn ghost" type="button" disabled={page <= 1} onClick={() => go(page - 1)}>Previous</button>
          <span>Page {page} of {pages} · {total} employees</span>
          <button className="btn ghost" type="button" disabled={page >= pages} onClick={() => go(page + 1)}>Next</button>
        </div>
      </section>
      {canWrite ? (
        <form className="panel form-grid" style={{ marginTop: 14 }} onSubmit={create}>
          <h2 style={{ gridColumn: "1 / -1" }}>Add employee</h2>
          <label className="field">Employee ID<input name="employee_id" required /></label>
          <label className="field">Full name<input name="full_name" required /></label>
          <label className="field">Department<input name="department" /></label>
          <label className="field">Job title<input name="job_title" /></label>
          <label className="field">Branch<select name="branch_id">{branches.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="field">Shift<select name="shift_id"><option value="">Default</option>{shifts.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <button className="btn" type="submit">Save</button>
        </form>
      ) : null}
    </>
  );
}
