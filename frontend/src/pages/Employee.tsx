import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

type Person = { employee_id: string; full_name: string; department: string; job_title: string; branch: string; shift: string; employment_status: string; email: string; phone: string };
type Row = { date: string; check_in: string; check_out: string; hours: number | null; hours_text?: string; status: string };

export function EmployeePage() {
  const { employeeId = "" } = useParams();
  const [person, setPerson] = useState<Person | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = decodeURIComponent(employeeId);
    api<Person>(`/api/v1/employees/${encodeURIComponent(id)}`).then(setPerson).catch((err) => setError(err.message));
    api<{ details: Row[] }>(`/api/v1/employees/${encodeURIComponent(id)}/attendance`)
      .then((body) => setRows(body.details || []))
      .catch(() => setRows([]));
  }, [employeeId]);

  if (error) return <p className="error">{error}</p>;
  if (!person) return <p>Loading…</p>;
  return (
    <>
      <div className="top">
        <div>
          <h1>{person.full_name}</h1>
          <p className="lede">{person.employee_id} · {person.job_title || "No title"} · {person.department || "No department"} · {person.branch} · {person.shift || "Default shift"}</p>
        </div>
        <span className={`badge ${person.employment_status}`}>{person.employment_status}</span>
      </div>
      <section className="panel">
        <h2>Attendance history</h2>
        <table>
          <thead><tr><th>Date</th><th>Check-in</th><th>Check-out</th><th>Hours</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.date}-${row.status}`} className={`row-${row.status.toLowerCase().replace(" ", "")}`}>
                <td>{row.date}</td><td>{row.check_in || "—"}</td>
                <td>{row.status === "Incomplete" ? <span className="no-checkout">No check-out</span> : row.check_out || "—"}</td>
                <td>{row.hours_text || "—"}</td>
                <td><span className={`badge ${row.status.toLowerCase().replace(" ", "")}`}>{row.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length ? <p className="empty">No calculated rows yet.</p> : null}
      </section>
    </>
  );
}
