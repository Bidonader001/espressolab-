import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { HolidaysLeave } from "../HolidaysLeave";
import { Branch, Shift } from "../types";

/** One line of the Shifts section of the branch form. `id` is null until the shift is saved. */
type ShiftRow = { key: string; id: number | null; name: string; start: string; end: string; grace: string };

let rowCounter = 0;
const newKey = () => `row-${++rowCounter}`;
const rowsOf = (branchId: number | null, list: Shift[]): ShiftRow[] =>
  branchId === null
    ? []
    : list.filter((shift) => shift.branch_id === branchId).map((shift) => ({
        key: newKey(),
        id: shift.id,
        name: shift.name,
        start: shift.start_time,
        end: shift.end_time,
        grace: shift.grace_minutes === null || shift.grace_minutes === undefined ? "" : String(shift.grace_minutes),
      }));

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Read "Sun-Thu" or "Sun,Mon,Tue" into a set of day names. Empty means the company default. */
function parseDays(text: string): Set<string> {
  const raw = (text || "").trim().toLowerCase();
  const out = new Set<string>();
  if (!raw) return out;
  const index = (name: string) => DAYS.findIndex((day) => day.toLowerCase() === name.trim().slice(0, 3));
  if (raw.includes("-") && !raw.includes(",")) {
    const [left, right] = raw.split("-");
    let a = index(left);
    const b = index(right);
    if (a >= 0 && b >= 0) {
      for (let guard = 0; guard < 7; guard++) {
        out.add(DAYS[a]);
        if (a === b) break;
        a = (a + 1) % 7;
      }
      return out;
    }
  }
  raw.replace(/;/g, ",").split(",").forEach((part) => {
    const at = index(part);
    if (at >= 0) out.add(DAYS[at]);
  });
  return out;
}

/** "Sun–Thu" when the days are consecutive, otherwise a comma list. */
function describeDays(text: string): string {
  const days = parseDays(text);
  if (!days.size) return "Company default";
  if (days.size === 7) return "Every day";
  for (let start = 0; start < 7; start++) {
    if (days.has(DAYS[start]) && !days.has(DAYS[(start + 6) % 7])) {
      let length = 0;
      while (days.has(DAYS[(start + length) % 7])) length++;
      if (length === days.size && length > 2) return `${DAYS[start]}–${DAYS[(start + length - 1) % 7]}`;
    }
  }
  return DAYS.filter((day) => days.has(day)).join(", ");
}

export function BranchesPage({ role = "viewer" }: { role?: string }) {
  const [items, setItems] = useState<Branch[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<Branch | null>(null);
  const [days, setDays] = useState<Set<string>>(new Set());
  const [rows, setRows] = useState<ShiftRow[]>([]);
  const [removed, setRemoved] = useState<number[]>([]);
  const [defaultChoice, setDefaultChoice] = useState("");
  const canWrite = role === "admin" || role === "supervisor";

  /** Fetch both lists again and return them so a form can be filled from fresh data. */
  async function refresh() {
    const [branches, shiftList] = await Promise.all([
      api<{ items: Branch[] }>("/api/v1/branches"),
      api<{ items: Shift[] }>("/api/v1/shifts"),
    ]);
    setItems(branches.items);
    setShifts(shiftList.items);
    return { branches: branches.items, shifts: shiftList.items };
  }
  function load() {
    refresh().catch((err) => setError(err.message));
  }
  useEffect(() => { load(); }, []);

  function startEdit(row: Branch | null, list: Shift[] = shifts) {
    setEditing(row);
    setDays(parseDays(row?.working_days || ""));
    setRows(rowsOf(row ? row.id : null, list));
    setRemoved([]);
    setDefaultChoice(row?.default_shift_id ? `id:${row.default_shift_id}` : "");
    setError("");
    setNotice("");
  }

  function addRow() {
    setRows((current) => [...current, { key: newKey(), id: null, name: "", start: "08:00", end: "16:00", grace: "" }]);
  }
  function changeRow(key: string, patch: Partial<ShiftRow>) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }
  function removeRow(row: ShiftRow) {
    if (row.id !== null && !window.confirm(`Remove the shift "${row.name}" when you save? People on it return to the default hours.`)) return;
    if (row.id !== null) setRemoved((current) => [...current, row.id as number]);
    if (defaultChoice === (row.id !== null ? `id:${row.id}` : `row:${row.key}`)) setDefaultChoice("");
    setRows((current) => current.filter((item) => item.key !== row.key));
  }

  function toggleDay(day: string) {
    const next = new Set(days);
    if (next.has(day)) next.delete(day);
    else next.add(day);
    setDays(next);
  }

  const daysText = () => DAYS.filter((day) => days.has(day)).join(",");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    setNotice("");
    const payload = {
      name: data.get("name"),
      code: data.get("code"),
      timezone: data.get("timezone") || "Europe/Istanbul",
      address: data.get("address"),
      working_days: daysText(),
      grace_minutes: data.get("grace_minutes") ? Number(data.get("grace_minutes")) : null,
      default_shift_id: defaultChoice.startsWith("id:") ? Number(defaultChoice.slice(3)) : null,
      work_start: "",
      work_end: "",
    };
    try {
      const branch = editing
        ? await api<Branch>(`/api/v1/branches/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await api<Branch>("/api/v1/branches", { method: "POST", body: JSON.stringify(payload) });
      for (const id of removed) {
        await api(`/api/v1/shifts/${id}`, { method: "DELETE" });
      }
      let defaultId = payload.default_shift_id;
      for (const row of rows) {
        const body = {
          name: row.name.trim(),
          start_time: row.start,
          end_time: row.end,
          grace_minutes: row.grace === "" ? null : Number(row.grace),
          branch_id: branch.id,
        };
        if (row.id !== null) {
          const before = shifts.find((shift) => shift.id === row.id);
          const same = before && before.name === body.name && before.start_time === body.start_time
            && before.end_time === body.end_time && (before.grace_minutes ?? null) === body.grace_minutes;
          if (!same) await api(`/api/v1/shifts/${row.id}`, { method: "PATCH", body: JSON.stringify(body) });
        } else {
          const created = await api<Shift>("/api/v1/shifts", { method: "POST", body: JSON.stringify(body) });
          if (defaultChoice === `row:${row.key}`) defaultId = created.id;
        }
      }
      if (defaultId !== payload.default_shift_id) {
        await api(`/api/v1/branches/${branch.id}`, { method: "PATCH", body: JSON.stringify({ ...payload, default_shift_id: defaultId }) });
      }
      const fresh = await refresh();
      const saved = fresh.branches.find((item) => item.id === branch.id) || branch;
      startEdit(saved, fresh.shifts);
      setNotice(editing
        ? `Saved ${String(payload.name)} with its shifts. Reports use the new settings straight away.`
        : `Added ${String(payload.name)}${rows.length ? " with its shifts" : ""}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
      load();
    }
  }

  async function remove(row: Branch) {
    if (!window.confirm(`Delete the branch "${row.name}"? This cannot be undone.`)) return;
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/branches/${row.id}`, { method: "DELETE" });
      if (editing?.id === row.id) startEdit(null);
      setNotice(`Deleted ${row.name}.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete");
    }
  }

  const shiftsOf = (branchId: number) => shifts.filter((row) => row.branch_id === branchId);
  const sharedShifts = shifts.filter((row) => row.branch_id === null);

  return (
    <>
      <div className="top"><div><h1>Branches</h1><p className="lede">Each branch keeps its own working days, grace period, timezone and shifts. Add the shifts inside the branch form. This page also holds holidays, approved leave and recalculation.</p></div></div>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      <section className="panel">
        <table>
          <thead><tr><th>Name</th><th>Code</th><th>Timezone</th><th>Working days</th><th>Grace</th><th>Shifts</th>{canWrite ? <th></th> : null}</tr></thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td><td>{row.code}</td><td>{row.timezone}</td><td>{describeDays(row.working_days)}</td><td>{row.grace_minutes ?? "Default"}</td>
                <td>
                  {shiftsOf(row.id).length ? shiftsOf(row.id).map((shift) => (
                    <div key={shift.id}>{shift.name} {shift.start_time}–{shift.end_time}{row.default_shift_id === shift.id ? " (default)" : ""}</div>
                  )) : "None"}
                </td>
                {canWrite ? (
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn ghost" type="button" onClick={() => startEdit(row)}>Edit</button>{" "}
                    <button className="btn ghost" type="button" onClick={() => remove(row)}>Delete</button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {canWrite ? (
        <form key={editing ? editing.id : "new"} className="panel form-grid" style={{ marginTop: 14 }} onSubmit={save}>
          <h2 style={{ gridColumn: "1 / -1" }}>{editing ? `Edit ${editing.name}` : "Add branch"}</h2>
          <label className="field">Name<input name="name" required defaultValue={editing?.name ?? ""} /></label>
          <label className="field">Code<input name="code" defaultValue={editing?.code ?? ""} /></label>
          <label className="field">Timezone<input name="timezone" defaultValue={editing?.timezone ?? "Europe/Istanbul"} /></label>
          <label className="field">Grace minutes<input name="grace_minutes" type="number" min="0" max="180" defaultValue={editing?.grace_minutes ?? ""} /></label>
          <div className="field wide" style={{ gridColumn: "1 / -1" }}>
            Working days
            <div className="daypicker">
              {DAYS.map((day) => (
                <label key={day} className={`daychip${days.has(day) ? " on" : ""}`}>
                  <input type="checkbox" checked={days.has(day)} onChange={() => toggleDay(day)} />
                  {day}
                </label>
              ))}
              <button className="btn ghost" type="button" onClick={() => setDays(new Set(["Sun", "Mon", "Tue", "Wed", "Thu"]))}>Sun–Thu</button>
              <button className="btn ghost" type="button" onClick={() => setDays(new Set(["Mon", "Tue", "Wed", "Thu", "Fri"]))}>Mon–Fri</button>
              <button className="btn ghost" type="button" onClick={() => setDays(new Set())}>Company default</button>
            </div>
            <small className="hint">Days not ticked are days off and appear as highlighted Weekend rows. Tick nothing to use the company working days.</small>
          </div>
          <div className="field wide" style={{ gridColumn: "1 / -1" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
              <span>Shifts (different working hours)</span>
              <button className="btn" type="button" aria-label="Add another shift" title="Add another shift" onClick={addRow}>+ Add shift</button>
            </div>
            {rows.length ? (
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                {rows.map((row) => (
                  <div key={row.key} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr auto", gap: 8, alignItems: "center" }}>
                    <input aria-label="Shift name" placeholder="Morning" required value={row.name} onChange={(event) => changeRow(row.key, { name: event.target.value })} />
                    <input aria-label="Shift starts" type="time" required value={row.start} onChange={(event) => changeRow(row.key, { start: event.target.value })} />
                    <input aria-label="Shift ends" type="time" required value={row.end} onChange={(event) => changeRow(row.key, { end: event.target.value })} />
                    <input aria-label="Shift grace minutes" type="number" min="0" max="180" placeholder="Grace (min)" value={row.grace} onChange={(event) => changeRow(row.key, { grace: event.target.value })} />
                    <button className="btn ghost" type="button" aria-label="Remove shift" title="Remove this shift" onClick={() => removeRow(row)}>✕</button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty" style={{ margin: "8px 0 0" }}>No shifts for this branch yet. Press + Add shift for each set of working hours (Morning, Evening, Night…).</p>
            )}
            <small className="hint">Late means the first punch is after the shift start plus the grace period. Shifts are saved with the branch.</small>
            {sharedShifts.length ? (
              <small className="hint">Also available to every branch: {sharedShifts.map((shift) => `${shift.name} ${shift.start_time}–${shift.end_time}`).join(", ")}.</small>
            ) : null}
          </div>
          <label className="field wide" style={{ gridColumn: "span 2" }}>
            Default shift
            <select value={defaultChoice} onChange={(event) => setDefaultChoice(event.target.value)}>
              <option value="">None (use the company hours)</option>
              {rows.map((row) => (
                <option key={row.key} value={row.id !== null ? `id:${row.id}` : `row:${row.key}`}>{row.name || "New shift"} {row.start}–{row.end}</option>
              ))}
              {sharedShifts.map((shift) => (
                <option key={`shared-${shift.id}`} value={`id:${shift.id}`}>{shift.name} {shift.start_time}–{shift.end_time} (all branches)</option>
              ))}
            </select>
            <small className="hint">Used for this branch's employees who have no shift of their own.</small>
          </label>
          <label className="field wide">Address<input name="address" defaultValue={editing?.address ?? ""} /></label>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" type="submit">{editing ? "Save changes" : "Save"}</button>
            {editing ? <button className="btn ghost" type="button" onClick={() => startEdit(null)}>Cancel</button> : null}
          </div>
        </form>
      ) : null}

      <HolidaysLeave branches={items} canWrite={canWrite} onNotice={setNotice} onError={setError} />
    </>
  );
}
