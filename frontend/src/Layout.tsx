import { NavLink, Outlet } from "react-router-dom";
import { Session } from "./App";
import { Logo } from "./Logo";

const STAFF = ["admin", "supervisor", "viewer"];
const LINKS: { to: string; label: string; end?: boolean; roles?: string[] }[] = [
  { to: "/employees", label: "Employees", roles: STAFF },
  { to: "/branches", label: "Branches", roles: STAFF },
  { to: "/devices", label: "Devices", roles: STAFF },
  { to: "/sync", label: "Sync history", roles: STAFF },
  { to: "/reports", label: "Reports" },
  { to: "/users", label: "Permissions", roles: ["admin"] },
  { to: "/audit", label: "Audit log", roles: ["admin", "supervisor"] },
  { to: "/settings", label: "Settings", roles: ["admin"] },
];

export function Layout({ session, onLogout }: { session: Session; onLogout: () => void }) {
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <Logo />
          <span>Attendance</span>
        </div>
        <nav className="nav">
          {LINKS.filter((link) => !link.roles || link.roles.includes(session.user.role)).map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          <div>{session.user.username}</div>
          <div>{session.user.role}</div>
          <button type="button" onClick={onLogout}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        {session.mustChange && session.user.role === "admin" ? (
          <div className="banner">The administrator password is still the default. Change it in Settings before using this system on a store network.</div>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
