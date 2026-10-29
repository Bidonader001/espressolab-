import { FormEvent, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, setSession, token, User } from "./api";
import { Layout } from "./Layout";
import { AttendancePage } from "./pages/Attendance";
import { AuditPage } from "./pages/Audit";
import { BranchesPage } from "./pages/Branches";
import { DashboardPage } from "./pages/Dashboard";
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
    navigate("/");
  }

  function logout() {
    setSession("");
    setUser(null);
    navigate("/login");
  }

  if (!ready) return <p className="main">Loading…</p>;
  return (
    <Routes>
      <Route path="/login" element={session ? <Navigate to="/" replace /> : <LoginPage onSubmit={login} />} />
      <Route element={session ? <Layout session={session} onLogout={logout} /> : <Navigate to="/login" replace />}>
        <Route index element={<DashboardPage />} />
        <Route path="attendance" element={<AttendancePage />} />
        <Route path="employees" element={<EmployeesPage role={session?.user.role || "viewer"} />} />
        <Route path="employees/:employeeId" element={<EmployeeDetailPage />} />
        <Route path="branches" element={<BranchesPage role={session?.user.role || "viewer"} />} />
        <Route path="devices" element={<DevicesPage role={session?.user.role || "viewer"} />} />
        <Route path="devices/:deviceId" element={<DeviceDetailPage role={session?.user.role || "viewer"} />} />
        <Route path="sync" element={<SyncPage />} />
        <Route path="rules" element={<Navigate to="/branches" replace />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="users" element={session?.user.role === "admin" ? <UsersPage /> : <Navigate to="/" replace />} />
        <Route path="audit" element={session?.user.role === "viewer" ? <Navigate to="/" replace /> : <AuditPage />} />
        <Route path="settings" element={session?.user.role === "admin" ? <SettingsPage mustChange={!!session?.mustChange} /> : <Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
