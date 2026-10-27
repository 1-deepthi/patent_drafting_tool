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
import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type User as FirebaseUser,
} from "firebase/auth";
import { apiFetch, setTokenProvider, ApiError } from "../lib/api";
import { FirebaseConfigError, firebaseAuth, isFirebaseConfigured } from "../lib/firebase";
import type { MeResponse, UserOut } from "../lib/types";

// Product requirement: a session ends after 30 minutes of inactivity. Firebase
// itself keeps the browser session alive and refreshes ID tokens in the
// background, so the idle rule is enforced here instead of through JWT expiry.
const IDLE_TIMEOUT_MS = 30 * 60_000;
const IDLE_CHECK_INTERVAL_MS = 60_000;
const ACTIVITY_EVENTS = ["mousedown", "keydown", "scroll", "touchstart"] as const;

type AuthStatus = "loading" | "unauthenticated" | "pending" | "approved";

interface AuthContextValue {
  status: AuthStatus;
  user: UserOut | null;
  permissions: string[];
  /** Set when Firebase Web config is missing from the build. */
  configError: string | null;
  /** Set when the API could not describe the signed-in user (e.g. 5xx). */
  sessionError: string | null;
  hasPermission: (code: string) => boolean;
  hasRole: (code: string) => boolean;
  signInWithGoogle: () => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PENDING_ACCOUNT_STATUSES = new Set(["Pending", "Rejected", "Suspended"]);

const GOOGLE_PROVIDER = new GoogleAuthProvider();
GOOGLE_PROVIDER.setCustomParameters({ prompt: "select_account" });

/** Pop-ups are blocked or unsupported in a few environments; fall back to a full redirect. */
function shouldFallBackToRedirect(error: unknown): boolean {
  const code = (error as { code?: string } | null)?.code;
  return (
    code === "auth/popup-blocked" ||
    code === "auth/popup-closed-by-user" ||
    code === "auth/cancelled-popup-request" ||
    code === "auth/operation-not-supported-in-this-environment"
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserOut | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [configError, setConfigError] = useState<string | null>(
    isFirebaseConfigured() ? null : new FirebaseConfigError().message,
  );
  const [sessionError, setSessionError] = useState<string | null>(null);
  const lastActivityRef = useRef<number>(Date.now());

  const clearSession = useCallback(() => {
    setUser(null);
    setPermissions([]);
    setStatus("unauthenticated");
  }, []);

  // Every API call asks Firebase for the current ID token, so a token that is
  // refreshed or revoked in another tab is picked up on the next request.
  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setTokenProvider(async () => null);
      return;
    }
    setTokenProvider(async () => {
      try {
        const current = firebaseAuth().currentUser;
        return current ? await current.getIdToken() : null;
      } catch {
        return null;
      }
    });
    return () => setTokenProvider(async () => null);
  }, []);

  const loadMe = useCallback(async () => {
    try {
      const me = await apiFetch<MeResponse>("/api/auth/me");
      setUser(me.user);
      setPermissions(me.permissions);
      setSessionError(null);
      setStatus(
        PENDING_ACCOUNT_STATUSES.has(me.user.account_status) ? "pending" : "approved",
      );
    } catch (error) {
      // A 401 means Firebase no longer accepts the session; anything else
      // (network, 5xx) also leaves us unable to describe the user.
      if (error instanceof ApiError && error.status === 401) {
        try {
          await signOut(firebaseAuth());
        } catch {
          // nothing else to do — the local state is cleared below
        }
      } else {
        setSessionError(
          error instanceof Error
            ? error.message
            : "The API could not load your account. Try again shortly.",
        );
      }
      clearSession();
    }
  }, [clearSession]);

  const handleSignedIn = useCallback(
    async (firebaseUser: FirebaseUser | null) => {
      if (!firebaseUser) {
        clearSession();
        return;
      }
      // Ensure the first request after a redirect sign-in carries a token.
      try {
        await firebaseUser.getIdToken();
      } catch {
        clearSession();
        return;
      }
      await loadMe();
    },
    [clearSession, loadMe],
  );

  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setStatus("unauthenticated");
      return;
    }
    let unsubscribe: (() => void) | undefined;
    try {
      unsubscribe = onAuthStateChanged(firebaseAuth(), (firebaseUser) => {
        void handleSignedIn(firebaseUser);
      });
    } catch (error) {
      setConfigError(
        error instanceof Error ? error.message : "Firebase could not be initialised.",
      );
      setStatus("unauthenticated");
    }
    return () => unsubscribe?.();
  }, [handleSignedIn]);

  const signInWithGoogle = useCallback(async () => {
    const auth = firebaseAuth();
    setSessionError(null);
    try {
      await signInWithPopup(auth, GOOGLE_PROVIDER);
    } catch (error) {
      if (shouldFallBackToRedirect(error)) {
        await signInWithRedirect(auth, GOOGLE_PROVIDER);
        return;
      }
      throw error;
    }
  }, []);

  const logout = useCallback(() => {
    // Best-effort ACK; the real session lives in Firebase, not the API.
    apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    try {
      void signOut(firebaseAuth());
    } catch {
      // already signed out or unconfigured
    }
    clearSession();
  }, [clearSession]);

  // Track activity for the idle rule.
  useEffect(() => {
    const markActive = () => {
      lastActivityRef.current = Date.now();
    };
    ACTIVITY_EVENTS.forEach((event) => window.addEventListener(event, markActive));
    return () =>
      ACTIVITY_EVENTS.forEach((event) => window.removeEventListener(event, markActive));
  }, []);

  useEffect(() => {
    if (status !== "approved") return;
    const interval = setInterval(() => {
      if (Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        logout();
      }
    }, IDLE_CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [status, logout]);

  const hasPermission = useCallback(
    (code: string) => permissions.includes(code),
    [permissions],
  );
  const hasRole = useCallback((code: string) => user?.roles.includes(code) ?? false, [user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      permissions,
      configError,
      sessionError,
      hasPermission,
      hasRole,
      signInWithGoogle,
      logout,
      refreshMe: loadMe,
    }),
    [
      status,
      user,
      permissions,
      configError,
      sessionError,
      hasPermission,
      hasRole,
      signInWithGoogle,
      logout,
      loadMe,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
