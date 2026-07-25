import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import AuthCallbackPage from "./pages/AuthCallbackPage";
import PendingApprovalPage from "./pages/PendingApprovalPage";
import NotAuthorizedPage from "./pages/NotAuthorizedPage";
import InnovatorDashboard from "./pages/InnovatorDashboard";
import PatentWorkflowPage from "./pages/PatentWorkflowPage";
import AgentDashboard from "./pages/AgentDashboard";
import DraftWorkspacePage from "./pages/DraftWorkspacePage";
import AdminDashboard from "./pages/AdminDashboard";
import SuperAdminDashboard from "./pages/SuperAdminDashboard";
import CalendarPage from "./pages/CalendarPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/pending-approval" element={<PendingApprovalPage />} />
          <Route path="/not-authorized" element={<NotAuthorizedPage />} />

          <Route
            path="/innovator/calendar"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/innovator/patents/:id"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <PatentWorkflowPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/innovator/*"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <InnovatorDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/calendar"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/patents/:id/draft"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <DraftWorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/*"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <AgentDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/calendar"
            element={
              <ProtectedRoute requireRole={["ADMIN"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/*"
            element={
              <ProtectedRoute requireRole={["ADMIN"]}>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/super-admin/calendar"
            element={
              <ProtectedRoute requireRole={["SUPER_ADMIN"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/super-admin/*"
            element={
              <ProtectedRoute requireRole={["SUPER_ADMIN"]}>
                <SuperAdminDashboard />
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
