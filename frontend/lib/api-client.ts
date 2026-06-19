/**
 * API client — typed fetch wrapper around the FastAPI backend.
 *
 * Responsibilities:
 * - Inject the Bearer access token from the `kg_at` HttpOnly cookie is NOT
 *   possible from the browser; instead the server-side auth helpers attach
 *   the token when proxying. For direct browser → API calls (client
 *   components), the access token is kept in memory + mirrored in a
 *   non-HttpOnly cookie so subsequent calls can read it.
 * - Refresh on 401 once, then propagate the error if refresh also fails.
 * - Surface the standard `{error:{code,message,details?}}` envelope as a
 *   typed `ApiError`.
 *
 * The actual cookie issuance happens server-side in `lib/auth.ts`
 * (`loginAction` / `verifyMagicLinkAction`).
 */

import type {
  AuditLogEntry,
  Citation,
  Document,
  DocumentPreview,
  DocumentStatus,
  DocumentUpdate,
  ErrorCode,
  ErrorDetail,
  ErrorResponseBody,
  FeedbackRequest,
  FeedbackResponse,
  FeedbackType,
  Group,
  GroupCreate,
  GroupUpdate,
  NoResultBlock,
  Page,
  PageMeta,
  Permission,
  QueryHistoryItem,
  QueryRequest,
  QueryResponse,
  Role,
  RoleAssignRequest,
  RoleCreate,
  RoleUpdate,
  Source,
  SourceCreate,
  SourceStatus,
  SourceType,
  SourceUpdate,
  SyncJob,
  SyncJobStatus,
  SystemSettings,
  SystemSettingsUpdate,
  TokenPair,
  User,
  UserInviteRequest,
  UserStatus,
  UserUpdate,
} from "./api-types";

// === Errors ===

export class ApiError extends Error {
  public readonly code: string;
  public readonly status: number;
  public readonly details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

// === Access-token storage (in-memory + cookie mirror) ===

const ACCESS_COOKIE = "kg_at";

let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  if (!match) return null;
  return decodeURIComponent(match.slice(name.length + 1));
}

function writeCookie(name: string, value: string, maxAgeSec: number): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAgeSec}; SameSite=Lax`;
}

function clearCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax`;
}

export function setAccessToken(
  token: string | null,
  expiresInSec?: number,
): void {
  accessToken = token;
  if (token) {
    const ttl = expiresInSec ?? 15 * 60;
    writeCookie(ACCESS_COOKIE, token, ttl);
  } else {
    clearCookie(ACCESS_COOKIE);
  }
}

export function getAccessToken(): string | null {
  if (accessToken) return accessToken;
  if (typeof document !== "undefined") {
    accessToken = readCookie(ACCESS_COOKIE);
  }
  return accessToken;
}

export function setRefreshToken(token: string | null): void {
  refreshToken = token;
}

export function getRefreshToken(): string | null {
  return refreshToken;
}

export function clearTokens(): void {
  accessToken = null;
  refreshToken = null;
  clearCookie(ACCESS_COOKIE);
}

// === Base URL ===

function baseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Check your .env file (see .env.example).",
    );
  }
  return url.replace(/\/+$/, "");
}

// === Request core ===

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Skip the auto-refresh dance (used by /auth/* itself). */
  skipRefresh?: boolean;
  /** When true, return the raw Response (for SSE). */
  raw?: boolean;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function doFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `${baseUrl()}${path}${buildQuery(opts.query)}`;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(opts.headers ?? {}),
  };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const token = getAccessToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
      credentials: "omit",
    });
  } catch (e) {
    throw new NetworkError(e instanceof Error ? e.message : "Network error");
  }

  // 401 → try refresh once (unless we're already on an auth endpoint).
  if (
    response.status === 401 &&
    !opts.skipRefresh &&
    refreshToken &&
    !path.startsWith("/api/v1/auth/")
  ) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      return doFetch<T>(path, opts);
    }
  }

  if (opts.raw) {
    return response as unknown as T;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      // non-JSON; fall through
    }
  }

  if (!response.ok) {
    const body = (parsed ?? {}) as Partial<ErrorResponseBody>;
    const err = body.error;
    throw new ApiError(
      response.status,
      err?.code ??
        `E${response.status === 401 ? "3" : response.status === 403 ? "4" : "1"}`,
      err?.message ?? `Request failed (${response.status})`,
      err?.details,
    );
  }

  return parsed as T;
}

async function refreshOnce(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      if (!refreshToken) return false;
      const resp = await fetch(`${baseUrl()}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!resp.ok) {
        clearTokens();
        return false;
      }
      const pair = (await resp.json()) as TokenPair;
      setAccessToken(pair.access_token, pair.expires_in);
      setRefreshToken(pair.refresh_token);
      return true;
    } catch {
      clearTokens();
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

// === Auth endpoints ===

export const authApi = {
  async login(email: string, password: string): Promise<TokenPair> {
    const pair = await doFetch<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
      skipRefresh: true,
    });
    setAccessToken(pair.access_token, pair.expires_in);
    setRefreshToken(pair.refresh_token);
    return pair;
  },

  async logout(): Promise<void> {
    try {
      await doFetch<void>("/api/v1/auth/logout", { method: "POST" });
    } finally {
      clearTokens();
    }
  },

  async requestMagicLink(email: string): Promise<void> {
    await doFetch<void>("/api/v1/auth/magic-link", {
      method: "POST",
      body: { email },
      skipRefresh: true,
    });
  },

  /** Server-side only — exchange magic-link token for a JWT pair. */
  async verifyMagicLink(token: string): Promise<TokenPair> {
    const pair = await doFetch<TokenPair>(
      `/api/v1/auth/magic-link/verify?token=${encodeURIComponent(token)}`,
      { skipRefresh: true },
    );
    setAccessToken(pair.access_token, pair.expires_in);
    setRefreshToken(pair.refresh_token);
    return pair;
  },

  async startOAuth(provider: "google" | "github"): Promise<string> {
    const r = await doFetch<{ authorize_url: string }>(
      `/api/v1/auth/oauth/${provider}`,
      { method: "POST", skipRefresh: true },
    );
    return r.authorize_url;
  },
};

// === Query endpoints ===

export const queryApi = {
  async ask(body: QueryRequest): Promise<QueryResponse> {
    return doFetch<QueryResponse>("/api/v1/query", { method: "POST", body });
  },
  async history(limit = 20, offset = 0): Promise<QueryHistoryItem[]> {
    return doFetch<QueryHistoryItem[]>("/api/v1/query/history", {
      query: { limit, offset },
    });
  },
  async get(id: string): Promise<QueryHistoryItem> {
    return doFetch<QueryHistoryItem>(`/api/v1/query/${id}`);
  },
};

export const feedbackApi = {
  async submit(body: FeedbackRequest): Promise<FeedbackResponse> {
    return doFetch<FeedbackResponse>("/api/v1/feedback", {
      method: "POST",
      body,
    });
  },
};

// === Documents ===

export const documentsApi = {
  async list(
    params: {
      source?: string;
      status?: string;
      owner?: string;
      language?: string;
      title_contains?: string;
      cursor?: string;
      limit?: number;
    } = {},
  ): Promise<Page<Document>> {
    return doFetch<Page<Document>>("/api/v1/documents", { query: params });
  },
  async get(id: string): Promise<Document> {
    return doFetch<Document>(`/api/v1/documents/${id}`);
  },
  async update(id: string, body: DocumentUpdate): Promise<Document> {
    return doFetch<Document>(`/api/v1/documents/${id}`, {
      method: "PATCH",
      body,
    });
  },
  async delete(id: string): Promise<void> {
    return doFetch<void>(`/api/v1/documents/${id}`, { method: "DELETE" });
  },
  async preview(id: string): Promise<DocumentPreview> {
    return doFetch<DocumentPreview>(`/api/v1/documents/${id}/preview`);
  },
};

// === Sources ===

export const sourcesApi = {
  async list(): Promise<Source[]> {
    return doFetch<Source[]>("/api/v1/sources");
  },
  async get(id: string): Promise<Source> {
    return doFetch<Source>(`/api/v1/sources/${id}`);
  },
  async create(body: SourceCreate): Promise<Source> {
    return doFetch<Source>("/api/v1/sources", { method: "POST", body });
  },
  async update(id: string, body: SourceUpdate): Promise<Source> {
    return doFetch<Source>(`/api/v1/sources/${id}`, {
      method: "PATCH",
      body,
    });
  },
  async delete(id: string): Promise<void> {
    return doFetch<void>(`/api/v1/sources/${id}`, { method: "DELETE" });
  },
  async triggerSync(id: string): Promise<SyncJob> {
    return doFetch<SyncJob>(`/api/v1/sources/${id}/sync`, { method: "POST" });
  },
};

// === Sync jobs ===

export const syncJobsApi = {
  async list(
    params: { source_id?: string; cursor?: string; limit?: number } = {},
  ): Promise<Page<SyncJob>> {
    return doFetch<Page<SyncJob>>("/api/v1/sync-jobs", { query: params });
  },
  async get(id: string): Promise<SyncJob> {
    return doFetch<SyncJob>(`/api/v1/sync-jobs/${id}`);
  },
  async retry(id: string): Promise<SyncJob> {
    return doFetch<SyncJob>(`/api/v1/sync-jobs/${id}/retry`, {
      method: "POST",
    });
  },
  stream(
    id: string,
    onEvent: (ev: {
      ts: string;
      stage?: string;
      progress?: number;
      message?: string;
    }) => void,
    signal?: AbortSignal,
  ): { abort: () => void } {
    const controller = new AbortController();
    let aborted = false;
    const token = getAccessToken();
    const url = `${baseUrl()}/api/v1/sync-jobs/${id}/stream`;
    (async () => {
      try {
        const res = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        // eslint-disable-next-line no-constant-condition
        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const lines = frame.split("\n");
            const dataLine = lines.find((l) => l.startsWith("data: "));
            if (dataLine) {
              try {
                onEvent(JSON.parse(dataLine.slice(6)));
              } catch {
                // ignore malformed frame
              }
            }
          }
        }
        // Release the underlying socket promptly on natural end.
        try {
          reader.releaseLock();
        } catch {
          // already released
        }
      } catch {
        // swallow — caller may resubscribe
      }
    })();
    if (signal) {
      signal.addEventListener("abort", () => {
        aborted = true;
        controller.abort();
      });
    }
    return {
      abort: () => {
        aborted = true;
        controller.abort();
      },
    };
  },
};

// === RBAC ===

export const usersApi = {
  async list(
    params: { cursor?: string; limit?: number; role?: string } = {},
  ): Promise<Page<User>> {
    return doFetch<Page<User>>("/api/v1/users", { query: params });
  },
  async invite(body: UserInviteRequest): Promise<User> {
    return doFetch<User>("/api/v1/users", { method: "POST", body });
  },
  async get(id: string): Promise<User> {
    return doFetch<User>(`/api/v1/users/${id}`);
  },
  async update(id: string, body: UserUpdate): Promise<User> {
    return doFetch<User>(`/api/v1/users/${id}`, { method: "PATCH", body });
  },
  async delete(id: string): Promise<void> {
    return doFetch<void>(`/api/v1/users/${id}`, { method: "DELETE" });
  },
  async assignRole(userId: string, roleId: string): Promise<void> {
    return doFetch<void>(`/api/v1/users/${userId}/roles`, {
      method: "POST",
      body: { role_id: roleId },
    });
  },
  async revokeRole(userId: string, roleId: string): Promise<void> {
    return doFetch<void>(`/api/v1/users/${userId}/roles/${roleId}`, {
      method: "DELETE",
    });
  },
};

export const rolesApi = {
  async list(
    params: { cursor?: string; limit?: number } = {},
  ): Promise<Page<Role>> {
    return doFetch<Page<Role>>("/api/v1/roles", { query: params });
  },
  async create(body: RoleCreate): Promise<Role> {
    return doFetch<Role>("/api/v1/roles", { method: "POST", body });
  },
  async get(id: string): Promise<Role> {
    return doFetch<Role>(`/api/v1/roles/${id}`);
  },
  async update(id: string, body: RoleUpdate): Promise<Role> {
    return doFetch<Role>(`/api/v1/roles/${id}`, { method: "PATCH", body });
  },
  async delete(id: string): Promise<void> {
    return doFetch<void>(`/api/v1/roles/${id}`, { method: "DELETE" });
  },
};

export const groupsApi = {
  async list(
    params: { cursor?: string; limit?: number } = {},
  ): Promise<Page<Group>> {
    return doFetch<Page<Group>>("/api/v1/groups", { query: params });
  },
  async create(body: GroupCreate): Promise<Group> {
    return doFetch<Group>("/api/v1/groups", { method: "POST", body });
  },
  async get(id: string): Promise<Group> {
    return doFetch<Group>(`/api/v1/groups/${id}`);
  },
  async update(id: string, body: GroupUpdate): Promise<Group> {
    return doFetch<Group>(`/api/v1/groups/${id}`, { method: "PATCH", body });
  },
  async delete(id: string): Promise<void> {
    return doFetch<void>(`/api/v1/groups/${id}`, { method: "DELETE" });
  },
  async addMember(groupId: string, userId: string): Promise<void> {
    return doFetch<void>(`/api/v1/groups/${groupId}/users`, {
      method: "POST",
      body: { user_id: userId },
    });
  },
  async removeMember(groupId: string, userId: string): Promise<void> {
    return doFetch<void>(`/api/v1/groups/${groupId}/users/${userId}`, {
      method: "DELETE",
    });
  },
  async addDocument(groupId: string, docId: string): Promise<void> {
    return doFetch<void>(`/api/v1/groups/${groupId}/documents`, {
      method: "POST",
      body: { document_id: docId },
    });
  },
  async removeDocument(groupId: string, docId: string): Promise<void> {
    return doFetch<void>(`/api/v1/groups/${groupId}/documents/${docId}`, {
      method: "DELETE",
    });
  },
};

// === Settings ===

export const settingsApi = {
  async get(): Promise<SystemSettings> {
    return doFetch<SystemSettings>("/api/v1/settings");
  },
  async update(body: SystemSettingsUpdate): Promise<SystemSettings> {
    return doFetch<SystemSettings>("/api/v1/settings", {
      method: "PATCH",
      body,
    });
  },
  async auditLog(
    params: {
      cursor?: string;
      limit?: number;
      user_id?: string;
      action?: string;
    } = {},
  ): Promise<Page<AuditLogEntry>> {
    return doFetch<Page<AuditLogEntry>>("/api/v1/settings/audit-log", {
      query: params,
    });
  },
};

// === Re-export all types for convenience ===
export type {
  AuditLogEntry,
  Citation,
  Document,
  DocumentPreview,
  DocumentStatus,
  DocumentUpdate,
  ErrorCode,
  ErrorDetail,
  ErrorResponseBody,
  FeedbackRequest,
  FeedbackResponse,
  FeedbackType,
  Group,
  GroupCreate,
  GroupUpdate,
  NoResultBlock,
  Page,
  PageMeta,
  Permission,
  QueryHistoryItem,
  QueryRequest,
  QueryResponse,
  Role,
  RoleAssignRequest,
  RoleCreate,
  RoleUpdate,
  Source,
  SourceCreate,
  SourceStatus,
  SourceType,
  SourceUpdate,
  SyncJob,
  SyncJobStatus,
  SystemSettings,
  SystemSettingsUpdate,
  TokenPair,
  User,
  UserInviteRequest,
  UserStatus,
  UserUpdate,
};
