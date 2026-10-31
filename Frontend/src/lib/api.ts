/** fetch wrapper: credentials include, X-CSRFToken from cookie, JSON errors. NFR-SEC-05 */

export class ApiError extends Error {
  status: number;
  errorCode: string;
  body: unknown;

  constructor(status: number, errorCode: string, message: string, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.body = body;
  }
}

export function getCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const parts = document.cookie.split(";");
  for (const part of parts) {
    const [rawKey, ...rest] = part.trim().split("=");
    if (rawKey === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const csrf = getCookie("csrftoken");
  if (csrf) {
    headers.set("X-CSRFToken", csrf);
  }

  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers,
  });

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    const body = data && typeof data === "object" ? (data as Record<string, unknown>) : {};
    throw new ApiError(
      response.status,
      String(body.error_code ?? "HTTP_ERROR"),
      String(body.message ?? response.statusText),
      data,
    );
  }

  return data as T;
}

export async function ensureCsrfCookie(): Promise<void> {
  await api("/api/csrf/");
}

export interface AuthUser {
  id: string;
  username: string;
}

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    const data = await api<{ user: AuthUser }>("/api/auth/me/");
    return data.user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const data = await api<{ user: AuthUser }>("/api/auth/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  return data.user;
}

export async function logout(): Promise<void> {
  await api("/api/auth/logout/", { method: "POST" });
}

export async function fetchCurrentTask<T = unknown>(): Promise<T> {
  return api<T>("/api/tasks/current/");
}

export async function fetchWsTicket(): Promise<string> {
  const data = await api<{ ticket: string }>("/api/ws-ticket/", { method: "POST" });
  return data.ticket;
}
