import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiFetch, googleLoginUrl, ApiError } from "../lib/api";
import type { TokenResponse } from "../lib/types";
import { ALL_ROLE_CODES } from "../lib/types";

const DEV_LOGIN_VISIBLE = import.meta.env.VITE_DEV_LOGIN_ENABLED === "true";

export default function LoginPage() {
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleCode, setRoleCode] = useState<string>("INNOVATOR");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await apiFetch<TokenResponse>("/api/auth/dev-login", {
        method: "POST",
        auth: false,
        body: JSON.stringify({ email, full_name: fullName || undefined, role_code: roleCode }),
      });
      loginWithToken(res);
      navigate("/auth/callback", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError(
          "Dev login is disabled on the backend (DEV_LOGIN_ENABLED is not set). Use Google sign-in, or enable it in backend/.env for local testing."
        );
      } else {
        setError(err instanceof Error ? err.message : "Dev login failed");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-slate-900">
            Patent Filing &amp; Lifecycle Platform
          </h1>
          <p className="mt-2 text-sm text-slate-500">Sign in to continue</p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <a
            href={googleLoginUrl()}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Sign in with Google
          </a>
          <p className="mt-3 text-center text-xs text-slate-400">
            New accounts require Super Admin approval before access is granted.
          </p>
        </div>

        {DEV_LOGIN_VISIBLE && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6">
            <p className="mb-4 text-xs font-medium uppercase tracking-wide text-amber-700">
              Dev login (local testing only)
            </p>
            <form onSubmit={handleDevLogin} className="space-y-3">
              <input
                type="email"
                required
                placeholder="email@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                type="text"
                placeholder="Full name (new users only)"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              <select
                value={roleCode}
                onChange={(e) => setRoleCode(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                {ALL_ROLE_CODES.map((code) => (
                  <option key={code} value={code}>
                    {code} (role for new users only)
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-700 disabled:opacity-50"
              >
                {submitting ? "Signing in…" : "Dev sign in"}
              </button>
            </form>
            {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
