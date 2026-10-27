const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/** Returns a fresh Firebase ID token for the signed-in user, or null. */
type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider = async () => null;

/**
 * Called once by AuthContext. Firebase ID tokens expire after an hour, so the
 * provider is asked for a token on every request instead of a cached string
 * being pushed in here.
 */
export function setTokenProvider(provider: TokenProvider) {
  tokenProvider = provider;
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await tokenProvider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Public limits reported by `GET /api/config/capabilities`. */
export interface RuntimeCapabilities {
  deployment_target: string;
  max_upload_size_bytes: number;
  max_request_body_bytes: number;
  pdf_generation_enabled: boolean;
}

let capabilitiesRequest: Promise<RuntimeCapabilities> | null = null;

/**
 * Deployment limits are fixed for the life of a backend instance, so one
 * request per page load is enough. A failed lookup is retried on the next call
 * rather than poisoning the cache.
 */
export function getRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  if (!capabilitiesRequest) {
    capabilitiesRequest = fetch(`${API_URL}/api/config/capabilities`)
      .then(async (response) => {
        if (!response.ok) {
          throw new ApiError(
            response.status,
            `Could not load deployment capabilities (${response.status})`,
          );
        }
        return (await response.json()) as RuntimeCapabilities;
      })
      .catch((error: unknown) => {
        capabilitiesRequest = null;
        throw error;
      });
  }
  return capabilitiesRequest;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ApiFetchOptions extends RequestInit {
  auth?: boolean; // defaults to true
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { auth = true, headers, ...rest } = options;

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
    ...(auth ? await authHeaders() : {}),
  };

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

/** For multipart uploads — apiFetch always sends Content-Type: application/json,
 * which breaks a multipart body, so this builds its own fetch with just the
 * Authorization header and lets the browser set the multipart boundary. */
export async function apiUpload<T>(
  path: string,
  file: File,
  fieldName = "upload",
  query?: Record<string, string | number | boolean>,
): Promise<T> {
  const capabilities = await getRuntimeCapabilities().catch(() => null);
  if (capabilities && file.size > capabilities.max_upload_size_bytes) {
    throw new ApiError(
      413,
      `"${file.name}" is ${formatFileSize(file.size)}; this deployment accepts files up to ` +
        `${formatFileSize(capabilities.max_upload_size_bytes)}.`,
    );
  }

  const formData = new FormData();
  formData.append(fieldName, file);

  const finalHeaders: Record<string, string> = { ...(await authHeaders()) };

  const qs = query
    ? "?" + new URLSearchParams(Object.entries(query).map(([k, v]) => [k, String(v)])).toString()
    : "";

  const response = await fetch(`${API_URL}${path}${qs}`, {
    method: "POST",
    headers: finalHeaders,
    body: formData,
  });

  if (!response.ok) {
    let detail = `Upload failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // not JSON — keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

/** For binary downloads (PDF/DOCX) — apiFetch always parses JSON, so this
 * fetches the blob directly, reads the filename from Content-Disposition,
 * and triggers a normal browser download via a throwaway <a> tag. */
export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const finalHeaders: Record<string, string> = { ...(await authHeaders()) };

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
