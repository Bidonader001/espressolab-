import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import { Branch } from "./types";

type Holiday = { id: number; holiday_date: string; name: string; branch: string };
type Leave = { id: number; employee_id: string; employee_name: string; work_date: string; note: string };

type Props = {
  branches: Branch[];
  canWrite: boolean;
  onNotice: (text: string) => void;
  onError: (text: string) => void;
};

export function HolidaysLeave({ branches, canWrite, onNotice, onError }: Props) {
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [leave, setLeave] = useState<Leave[]>([]);
  const [busy, setBusy] = useState(false);

  function load() {
    api<{ items: Holiday[] }>("/api/v1/holidays").then((body) => setHolidays(body.items)).catch((err) => onError(err.message));
    api<{ items: Leave[] }>("/api/v1/leave").then((body) => setLeave(body.items)).catch((err) => onError(err.message));
  }
  useEffect(() => { load(); }, []);

  async function save(path: string, body: unknown, form: HTMLFormElement, done: string) {
    onError("");
    onNotice("");
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      form.reset();
      onNotice(done);
      load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not save");
    }
  }

  async function remove(path: string, done: string) {
    onError("");
    onNotice("");
    try {
      await api(path, { method: "DELETE" });
      onNotice(done);
      load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not delete");
    }
  }

  async function recalculate() {
    if (!window.confirm("Rebuild every employee's sessions from the stored punches? The punches themselves are not touched.")) return;
    setBusy(true);
    onError("");
    onNotice("");
    try {
      await api("/api/v1/attendance/recalculate", { method: "POST" });
      onNotice("Attendance was recalculated from the stored punches.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not recalculate");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <section className="panel">
          <h2>Holidays</h2>
          <p className="hint">A holiday is not counted as an absence. Pick a branch to limit it to that branch.</p>
          <table>
            <tbody>
              {holidays.map((row) => (
                <tr key={row.id}>
                  <td>{row.holiday_date}</td><td>{row.name}</td><td>{row.branch || "All branches"}</td>
                  {canWrite ? <td><button className="btn ghost" type="button" onClick={() => remove(`/api/v1/holidays/${row.id}`, `Removed ${row.name}.`)}>Remove</button></td> : null}
                </tr>
              ))}
            </tbody>
          </table>
          {!holidays.length ? <p className="empty">No holidays yet.</p> : null}
          {canWrite ? (
            <form className="stack" onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              save("/api/v1/holidays", { holiday_date: data.get("holiday_date"), name: data.get("name"), branch_id: Number(data.get("branch_id")) || null }, form, `Added holiday ${String(data.get("name"))}.`);
            }}>
              <label className="field">Date<input name="holiday_date" type="date" required /></label>
              <label className="field">Name<input name="name" required /></label>
              <label className="field">Branch<select name="branch_id"><option value="">All branches</option>{branches.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
              <button className="btn" type="submit">Add holiday</button>
            </form>
          ) : null}
        </section>
        <section className="panel">
          <h2>Approved leave</h2>
          <p className="hint">Leave shows as On Leave in reports and is not counted as an absence.</p>
          <table>
            <tbody>
              {leave.map((row) => (
                <tr key={row.id}>
                  <td>{row.work_date}</td><td>{row.employee_name || row.employee_id}</td><td>{row.note}</td>
                  {canWrite ? <td><button className="btn ghost" type="button" onClick={() => remove(`/api/v1/leave/${row.id}`, "Leave removed.")}>Remove</button></td> : null}
                </tr>
              ))}
            </tbody>
          </table>
          {!leave.length ? <p className="empty">No approved leave yet.</p> : null}
          {canWrite ? (
            <form className="stack" onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              save("/api/v1/leave", { employee_id: data.get("employee_id"), work_date: data.get("work_date"), note: data.get("note") }, form, "Leave approved.");
            }}>
              <label className="field">Employee ID<input name="employee_id" required /></label>
              <label className="field">Date<input name="work_date" type="date" required /></label>
              <label className="field">Note<input name="note" /></label>
              <button className="btn" type="submit">Approve leave</button>
            </form>
          ) : null}
        </section>
      </div>
      {canWrite ? (
        <section className="panel" style={{ marginTop: 14 }}>
          <h2>Recalculate attendance</h2>
          <p className="hint">Late means the first punch is later than the shift start plus the grace period. A missing punch stays Incomplete. Recalculating rebuilds the sessions from the stored punches and leaves the original device logs in place. Shift and branch changes already do this for the people they affect.</p>
          <button className="btn" type="button" disabled={busy} onClick={recalculate}>Recalculate attendance</button>
        </section>
      ) : null}
    </>
  );
}
