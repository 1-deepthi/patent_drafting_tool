import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { NotificationBell } from "./NotificationBell";
import { ROLE_HOME } from "../lib/types";

export function DashboardShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const { user, logout } = useAuth();
  const homeRole = user?.roles[0];
  const calendarPath = homeRole ? `${ROLE_HOME[homeRole]}/calendar` : "/calendar";

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
            <p className="text-xs text-slate-500">
              {user?.full_name} · {user?.email} · {user?.roles.join(", ")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to={calendarPath}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Calendar
            </Link>
            <NotificationBell />
            <button
              onClick={logout}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
