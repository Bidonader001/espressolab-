import { FormEvent, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, setSession, token, User } from "./api";
import { Layout } from "./Layout";
import { AuditPage } from "./pages/Audit";
import { BranchesPage } from "./pages/Branches";
import { DevicePage as DeviceDetailPage } from "./pages/Device";
import { DevicesPage } from "./pages/Devices";
import { EmployeePage as EmployeeDetailPage } from "./pages/Employee";
import { EmployeesPage } from "./pages/Employees";
import { LoginPage } from "./pages/Login";
import { ReportsPage } from "./pages/Reports";
import { SettingsPage } from "./pages/Settings";
import { SyncPage } from "./pages/Sync";
import { UsersPage } from "./pages/Users";

export type Session = { user: User; mustChange: boolean; company: string };

export function App() {
  const [session, setUser] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!token()) {
      setReady(true);
      return;
    }
    api<{ user: User; must_change_password: boolean; company_name: string }>("/api/v1/auth/me")
      .then((body) => setUser({ user: body.user, mustChange: body.must_change_password, company: body.company_name }))
      .catch(() => setSession(""))
      .finally(() => setReady(true));
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = await api<{ token: string; user: User }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
    });
    setSession(body.token);
    const me = await api<{ user: User; must_change_password: boolean; company_name: string }>("/api/v1/auth/me");
    setUser({ user: me.user, mustChange: me.must_change_password, company: me.company_name });
    navigate(me.user.role === "hr" ? "/reports" : "/employees");
  }

  function logout() {
    setSession("");
    setUser(null);
    navigate("/login");
  }

  if (!ready) return <p className="main">Loading…</p>;
  return (
    <Routes>
      <Route path="/login" element={session ? <Navigate to={session.user.role === "hr" ? "/reports" : "/employees"} replace /> : <LoginPage onSubmit={login} />} />
      <Route element={session ? <Layout session={session} onLogout={logout} /> : <Navigate to="/login" replace />}>
        <Route index element={<Navigate to={session?.user.role === "hr" ? "/reports" : "/employees"} replace />} />
        <Route path="attendance" element={<Navigate to={session?.user.role === "hr" ? "/reports" : "/employees"} replace />} />
        <Route path="employees" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <EmployeesPage role={session?.user.role || "viewer"} />} />
        <Route path="employees/:employeeId" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <EmployeeDetailPage />} />
        <Route path="branches" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <BranchesPage role={session?.user.role || "viewer"} />} />
        <Route path="devices" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <DevicesPage role={session?.user.role || "viewer"} />} />
        <Route path="devices/:deviceId" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <DeviceDetailPage role={session?.user.role || "viewer"} />} />
        <Route path="sync" element={session?.user.role === "hr" ? <Navigate to="/reports" replace /> : <SyncPage />} />
        <Route path="rules" element={<Navigate to={session?.user.role === "hr" ? "/reports" : "/branches"} replace />} />
        <Route path="reports" element={<ReportsPage role={session?.user.role || "viewer"} />} />
        <Route path="users" element={session?.user.role === "admin" ? <UsersPage /> : <Navigate to={session?.user.role === "hr" ? "/reports" : "/employees"} replace />} />
        <Route path="audit" element={session?.user.role === "admin" || session?.user.role === "supervisor" ? <AuditPage /> : <Navigate to={session?.user.role === "hr" ? "/reports" : "/employees"} replace />} />
        <Route path="settings" element={session?.user.role === "admin" ? <SettingsPage mustChange={!!session?.mustChange} /> : <Navigate to={session?.user.role === "hr" ? "/reports" : "/employees"} replace />} />
      </Route>
    </Routes>
  );
}
