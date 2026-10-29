import { FormEvent, useEffect, useRef, useState } from "react";
import { api, blobUrl, download, qs } from "../api";

type Meta = { reports: string[]; formats: string[]; branches: string[]; departments: string[]; hours_note: string; omitted: string[] };
type Preview = {
  title: string;
  start: string;
  end: string;
  branch: string;
  department: string;
  hours_note: string;
  columns: string[];
  keys: string[];
  rows: { cells: (string | number)[]; status: string }[];
  count: number;
  page: number;
  page_size: number;
  summary: { employee: string; employee_id: string; branch: string; days_present: number; late_arrivals: number; absences: number; incomplete_days: number; total_text: string }[];
  total_hours: string;
  incomplete_days: number;
};

const PAGE_SIZE = 100;
const slug = (value: string) => value.toLowerCase().replace(/\s+/g, "");

export function ReportsPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const params = useRef<Record<string, string>>({});
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    api<Meta>("/api/v1/exports/meta").then(setMeta).catch((err) => setError(err.message));
  }, []);

  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  function values(form: HTMLFormElement) {
    const data = new FormData(form);
    return {
      report: String(data.get("report") || "monthly"),
      format: String(data.get("format") || "xlsx"),
      start_date: String(data.get("start_date") || ""),
      end_date: String(data.get("end_date") || ""),
      branch: String(data.get("branch") || ""),
      department: String(data.get("department") || ""),
      employee_id: String(data.get("employee_id") || ""),
      status: String(data.get("status") || ""),
      source: String(data.get("source") || ""),
      device_id: String(data.get("device_id") || ""),
      include_inactive: String(data.get("include_inactive") || ""),
    };
  }

  async function loadPreview(next: number) {
    setBusy(true);
    setError("");
    try {
      const body = await api<Preview>(`/api/v1/exports/preview${qs({ ...params.current, page: next, page_size: PAGE_SIZE })}`);
      setPreview(body);
      setPage(next);
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  function showPreview() {
    if (!formRef.current) return;
    params.current = values(formRef.current);
    setPdfUrl("");
    loadPreview(1);
  }

  async function showPdf() {
    if (!formRef.current) return;
    setError("");
    setBusy(true);
    try {
      const current = values(formRef.current);
      const path = current.report === "employees" ? `/api/v1/exports/employees${qs({ ...current, format: "pdf" })}` : `/api/v1/exports${qs({ ...current, format: "pdf" })}`;
      setPdfUrl(await blobUrl(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function exportFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const current = values(event.currentTarget);
      const path = current.report === "employees" ? `/api/v1/exports/employees${qs(current)}` : `/api/v1/exports${qs(current)}`;
      await download(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    }
  }

  const pages = preview ? Math.max(1, Math.ceil(preview.count / PAGE_SIZE)) : 1;

  return (
    <>
      <div className="top"><div><h1>Reports</h1><p className="lede">{meta?.hours_note} Use Preview to check the rows on screen before you download. The download uses people read from the attendance machines and the punches stored on those machines.</p></div></div>
      {meta?.omitted?.length ? <p className="banner">Not in these files: {meta.omitted.join(", ")}.</p> : null}
      <form id="export-form" ref={formRef} className="panel form-grid" onSubmit={exportFile}>
        <label className="field">Report
          <select name="report">{(meta?.reports || ["daily", "monthly"]).map((name) => <option key={name}>{name}</option>)}</select>
        </label>
        <label className="field">Format
          <select name="format">{(meta?.formats || ["xlsx", "csv", "pdf"]).map((name) => <option key={name}>{name}</option>)}</select>
        </label>
        <label className="field">From<input name="start_date" type="date" /></label>
        <label className="field">To<input name="end_date" type="date" /></label>
        <label className="field">Branch
          <select name="branch"><option value="">All</option>{meta?.branches.map((name) => <option key={name}>{name}</option>)}</select>
        </label>
        <label className="field">Department
          <select name="department"><option value="">All</option>{meta?.departments.map((name) => <option key={name}>{name}</option>)}</select>
        </label>
        <label className="field">People
          <select name="source" defaultValue="device">
            <option value="device">From the attendance machines</option>
            <option value="">Everyone in the directory</option>
          </select>
        </label>
        <label className="field">Inactive employees
          <select name="include_inactive" defaultValue="">
            <option value="">Left out</option>
            <option value="1">Included</option>
          </select>
        </label>
        <label className="field">Employee ID<input name="employee_id" /></label>
        <label className="field">Status
          <select name="status"><option value="">All</option>{["Present", "Late", "Absent", "Incomplete", "On Leave", "Weekend"].map((name) => <option key={name}>{name}</option>)}</select>
        </label>
        <div className="row-actions">
          <button className="btn ghost" type="button" disabled={busy} onClick={showPreview}>Preview</button>
          <button className="btn ghost" type="button" disabled={busy} onClick={showPdf}>Preview as PDF</button>
          <button className="btn" type="submit">Download</button>
        </div>
      </form>
      {error ? <p className="error">{error}</p> : null}

      {pdfUrl ? (
        <section className="panel" style={{ marginTop: 14 }}>
          <div className="row-actions" style={{ justifyContent: "space-between" }}>
            <h2>PDF preview</h2>
            <button className="btn ghost" type="button" onClick={() => setPdfUrl("")}>Close</button>
          </div>
          <iframe className="preview-frame" title="PDF preview" src={pdfUrl} />
        </section>
      ) : null}

      {preview ? (
        <section className="panel" style={{ marginTop: 14 }}>
          <h2>{preview.title}</h2>
          <div className="preview-meta">
            {preview.start && preview.title ? <span>{preview.start} to {preview.end}</span> : null}
            <span>Branch: {preview.branch}</span>
            <span>Department: {preview.department}</span>
            <span><strong>{preview.count}</strong> rows</span>
            {preview.total_hours ? <span>Total hours <strong>{preview.total_hours}</strong></span> : null}
            {preview.incomplete_days ? <span>{preview.incomplete_days} incomplete days (no check-out, no hours)</span> : null}
          </div>
          <div className="scroll-x">
            <table>
              <thead><tr>{preview.columns.map((name) => <th key={name}>{name}</th>)}</tr></thead>
              <tbody>
                {preview.rows.map((row, index) => (
                  <tr key={index} className={row.status ? `row-${slug(row.status)}` : ""}>
                    {row.cells.map((cell, col) => {
                      const key = preview.keys[col];
                      if (key === "status") return <td key={col}><span className={`badge ${slug(String(cell))}`}>{cell}</span></td>;
                      if (key === "check_out" && cell === "No check-out") return <td key={col}><span className="no-checkout">No check-out</span></td>;
                      return <td key={col}>{cell === "" ? "—" : cell}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!preview.rows.length ? <p className="empty">Nothing matches these filters, so the download would be empty.</p> : null}
          <div className="pager">
            <button className="btn ghost" type="button" disabled={busy || page <= 1} onClick={() => loadPreview(page - 1)}>Previous</button>
            <span>Page {page} of {pages}</span>
            <button className="btn ghost" type="button" disabled={busy || page >= pages} onClick={() => loadPreview(page + 1)}>Next</button>
          </div>
          {preview.summary.length ? (
            <details style={{ marginTop: 16 }}>
              <summary>Employee summary ({preview.summary.length})</summary>
              <div className="scroll-x">
                <table>
                  <thead><tr><th>Employee</th><th>Branch</th><th>Days present</th><th>Late arrivals</th><th>Absences</th><th>Incomplete days</th><th>Total hours</th></tr></thead>
                  <tbody>
                    {preview.summary.map((row) => (
                      <tr key={row.employee_id}><td>{row.employee}</td><td>{row.branch}</td><td>{row.days_present}</td><td>{row.late_arrivals}</td><td>{row.absences}</td><td>{row.incomplete_days}</td><td>{row.total_text}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
