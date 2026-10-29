import { useEffect, useState } from "react";
import { api } from "../api";

type Dash = {
  date: string;
  timezone: string;
  present: number;
  late: number;
  missing_punches: number;
  absent: number;
  active_employees: number;
  last_sync_at: string | null;
  branch_stats: { branch: string; employees: number; present: number; late: number; absent: number }[];
  devices: { total: number; connectivity: Record<string, number>; unmapped_users: number };
  recent_errors: { id: number; message: string; finished_at: string | null }[];
  trend: { date: string; present: number }[];
  hours_note: string;
};

export function DashboardPage() {
  const [data, setData] = useState<Dash | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Dash>("/api/v1/dashboard")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading…</p>;
  const max = Math.max(1, ...data.trend.map((day) => day.present));
  const cards = [
    ["Present today", data.present, data.date],
    ["Absent today", data.absent, data.timezone],
    ["Late arrivals", data.late, "After the grace period"],
    ["Missing punches", data.missing_punches, "Open check-in or check-out"],
    ["Active employees", data.active_employees, "Directory"],
    ["Devices", data.devices.total, `${data.devices.unmapped_users} unmapped user IDs`],
  ];
  return (
    <>
      <div className="top">
        <div>
          <h1>Today</h1>
          <p className="lede">{data.hours_note}</p>
        </div>
      </div>
      <section className="cards">
        {cards.map(([label, value, note], index) => (
          <article className={index === 0 ? "card feature" : "card"} key={String(label)}>
            <div className="k">{label}</div>
            <div className="v">{value}</div>
            <div className="s">{note}</div>
          </article>
        ))}
      </section>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <section className="panel">
          <h2>This month</h2>
          <div className="bars" aria-label="Daily present counts">
            {data.trend.slice(-14).map((day) => (
              <div key={day.date} style={{ height: `${Math.max(4, (day.present / max) * 120)}px` }} title={`${day.date}: ${day.present}`}>
                <span>{day.date.slice(8)}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <h2>Devices</h2>
          <p>Last successful sync: {data.last_sync_at || "none yet"}</p>
          <p>{Object.entries(data.devices.connectivity).map(([name, count]) => `${name} ${count}`).join(" · ") || "No devices"}</p>
          {data.recent_errors.length ? (
            <ul>
              {data.recent_errors.map((row) => (
                <li key={row.id}>{row.message}</li>
              ))}
            </ul>
          ) : (
            <p className="empty">No recent sync errors.</p>
          )}
        </section>
      </div>
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Branches</h2>
        <table>
          <thead>
            <tr><th>Branch</th><th>Employees</th><th>Present</th><th>Late</th><th>Absent</th></tr>
          </thead>
          <tbody>
            {data.branch_stats.map((row) => (
              <tr key={row.branch}>
                <td>{row.branch}</td><td>{row.employees}</td><td>{row.present}</td><td>{row.late}</td><td>{row.absent}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
