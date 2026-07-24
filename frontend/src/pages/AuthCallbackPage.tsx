import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../lib/api";
import { setAuthToken } from "../lib/api";
import type { MeResponse } from "../lib/types";
import { ROLE_HOME } from "../lib/types";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_failed: "Google sign-in failed. Please try again.",
  oauth_no_email: "Google did not share an email address with us. Please try again.",
  account_conflict:
    "An account already exists for this email under a different Google identity. Contact your Super Admin.",
};

export default function AuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refreshMe } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const token = params.get("token");
    const errParam = params.get("error");

    if (errParam) {
      setError(OAUTH_ERROR_MESSAGES[errParam] || "Sign-in failed. Please try again.");
      return;
    }

    async function finish() {
      if (token) {
        setAuthToken(token);
        localStorage.setItem("patent_platform_token", token);
      }
      try {
        const me = await apiFetch<MeResponse>("/api/auth/me");
        await refreshMe();
        if (me.user.account_status !== "Approved") {
          navigate("/pending-approval", { replace: true });
          return;
        }
        const home = me.user.roles.map((r) => ROLE_HOME[r]).find(Boolean) || "/";
        navigate(home, { replace: true });
      } catch {
        navigate("/login", { replace: true });
      }
    }

    finish();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 px-4 text-center">
        <p className="max-w-sm text-sm text-red-600">{error}</p>
        <a href="/login" className="text-sm font-medium text-blue-600 hover:underline">
          Back to sign in
        </a>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
      Finishing sign-in…
    </div>
  );
}
