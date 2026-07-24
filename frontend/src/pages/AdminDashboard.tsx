// Admin route tree — user approvals belong to Super Admin only per spec
// (see handover §2/§3.1); Admin's own scope beyond RBAC is built out in
// later phases as features land.

import { DashboardShell } from "../components/DashboardShell";

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin">
      <p className="text-sm text-slate-500">
        Signed in successfully. Admin-specific workflows are built out in later phases.
      </p>
    </DashboardShell>
  );
}
