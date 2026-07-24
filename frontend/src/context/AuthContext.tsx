import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { apiFetch, setAuthToken } from "../lib/api";
import type { MeResponse, TokenResponse, UserOut } from "../lib/types";

const TOKEN_STORAGE_KEY = "patent_platform_token";
// How often we check whether the user has been active and, if so, silently
// refresh the token. This implements the "30-minute inactivity timeout"
// spec as a sliding JWT expiry: each refresh mints a fresh 30-minute
// window. If the person is genuinely idle for 30 minutes, no refresh
// happens, the token's `exp` passes, and the next API call/refresh 401s.
const ACTIVITY_CHECK_INTERVAL_MS = 60_000; // 1 minute
const ACTIVITY_EVENTS = ["mousedown", "keydown", "scroll", "touchstart"] as const;

type AuthStatus = "loading" | "unauthenticated" | "pending" | "approved";

interface AuthContextValue {
  status: AuthStatus;
  user: UserOut | null;
  permissions: string[];
  hasPermission: (code: string) => boolean;
  hasRole: (code: string) => boolean;
  loginWithToken: (res: TokenResponse) => void;
  logout: () => void;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserOut | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const lastActivityRef = useRef<number>(Date.now());
  const lastRefreshRef = useRef<number>(0);

  const applyToken = useCallback((token: string | null) => {
    setAuthToken(token);
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }, []);

  const loadMe = useCallback(async () => {
    try {
      const me = await apiFetch<MeResponse>("/api/auth/me");
      setUser(me.user);
      setPermissions(me.permissions);
      setStatus(me.user.account_status === "Approved" ? "approved" : "pending");
    } catch {
      applyToken(null);
      setUser(null);
      setPermissions([]);
      setStatus("unauthenticated");
    }
  }, [applyToken]);

  // Bootstrap from localStorage on first load.
  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!stored) {
      setStatus("unauthenticated");
      return;
    }
    setAuthToken(stored);
    loadMe();
  }, [loadMe]);

  const loginWithToken = useCallback(
    (res: TokenResponse) => {
      applyToken(res.access_token);
      setUser(res.user);
      lastRefreshRef.current = Date.now();
      loadMe();
    },
    [applyToken, loadMe]
  );

  const logout = useCallback(() => {
    apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {
      // best-effort — we clear client state regardless
    });
    applyToken(null);
    setUser(null);
    setPermissions([]);
    setStatus("unauthenticated");
  }, [applyToken]);

  // Track user activity.
  useEffect(() => {
    const markActive = () => {
      lastActivityRef.current = Date.now();
    };
    ACTIVITY_EVENTS.forEach((evt) => window.addEventListener(evt, markActive));
    return () => ACTIVITY_EVENTS.forEach((evt) => window.removeEventListener(evt, markActive));
  }, []);

  // Sliding-expiry refresh loop.
  useEffect(() => {
    if (status !== "approved") return;

    const interval = setInterval(async () => {
      const idleForMs = Date.now() - lastActivityRef.current;
      if (idleForMs > 30 * 60_000) return; // idle too long — let it expire naturally

      try {
        const res = await apiFetch<TokenResponse>("/api/auth/refresh", { method: "POST" });
        applyToken(res.access_token);
        lastRefreshRef.current = Date.now();
      } catch {
        // Token already expired or invalid — force logout.
        applyToken(null);
        setUser(null);
        setPermissions([]);
        setStatus("unauthenticated");
      }
    }, ACTIVITY_CHECK_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [status, applyToken]);

  const hasPermission = useCallback((code: string) => permissions.includes(code), [permissions]);
  const hasRole = useCallback((code: string) => user?.roles.includes(code) ?? false, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      permissions,
      hasPermission,
      hasRole,
      loginWithToken,
      logout,
      refreshMe: loadMe,
    }),
    [status, user, permissions, hasPermission, hasRole, loginWithToken, logout, loadMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
