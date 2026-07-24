const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

let currentToken: string | null = null;

/** Called by AuthContext whenever the token changes (login/refresh/logout). */
export function setAuthToken(token: string | null) {
  currentToken = token;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface ApiFetchOptions extends RequestInit {
  auth?: boolean; // defaults to true
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { auth = true, headers, ...rest } = options;

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (auth && currentToken) {
    finalHeaders["Authorization"] = `Bearer ${currentToken}`;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function googleLoginUrl(): string {
  return `${API_URL}/api/auth/google/login`;
}

/** For binary downloads (PDF/DOCX) — apiFetch always parses JSON, so this
 * fetches the blob directly, reads the filename from Content-Disposition,
 * and triggers a normal browser download via a throwaway <a> tag. */
export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const finalHeaders: Record<string, string> = {};
  if (currentToken) finalHeaders["Authorization"] = `Bearer ${currentToken}`;

  const response = await fetch(`${API_URL}${path}`, { headers: finalHeaders });
  if (!response.ok) {
    let detail = `Download failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // not JSON — keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : fallbackFilename;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
