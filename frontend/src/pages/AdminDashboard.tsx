// Admin route tree — user approvals belong to Super Admin only per spec
// (see handover §2/§3.1). Templates management (NEW — closes open item
// #24) is the first real Admin-scoped workflow; more land here as later
// phases add features.

import { DashboardShell } from "../components/DashboardShell";
import { TemplatesPanel } from "../components/TemplatesPanel";

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin">
      <div className="mb-6 border-b border-slate-200 pb-2">
        <h2 className="text-sm font-semibold text-slate-900">Document Templates</h2>
        <p className="text-xs text-slate-500">
          Upload and manage the .docx templates used when generating patent documents.
        </p>
      </div>
      <TemplatesPanel />
    </DashboardShell>
  );
}
