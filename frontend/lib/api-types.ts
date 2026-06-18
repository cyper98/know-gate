/**
 * API type definitions — mirror the FastAPI Pydantic response models.
 *
 * These types are hand-written to match the backend contract. If the backend
 * drifts, regenerate from `/api/v1/openapi.json` (a `pnpm run codegen` script
 *
 * Error envelope matches `backend/app/api/responses.py` (`ErrorCode` E1-E15).
 */

export type ErrorCode =
  | "E1" // INTERNAL (500)
  | "E2" // BAD_REQUEST (400) — also Pydantic validation
  | "E3" // UNAUTHORIZED (401)
  | "E4" // FORBIDDEN (403)
  | "E5" // NOT_FOUND (404)
  | "E6" // CONFLICT (409)
  | "E7" // RATE_LIMITED (429)
  | "E8" // SERVICE_UNAVAILABLE (503)
  | "E9" // PERMISSION_DENIED_DATA (403)
  | "E10" // NO_ANSWER (200)
  | "E11" // EXTERNAL_API_ERROR (502/504)
  | "E12" // INVALID_STATE (409)
  | "E13" // QUOTA_EXCEEDED (402)
  | "E14" // DEPRECATED (410)
  | "E15"; // UNPROCESSABLE (422)

export interface ErrorDetail {
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface ErrorResponseBody {
  error: ErrorDetail;
}

export interface PageMeta {
  total?: number;
  next_cursor?: string;
  limit?: number;
}

export interface Page<T> {
  data: T[];
  meta?: PageMeta;
}

// === Auth ===

export type UserStatus = "active" | "inactive" | "pending";

export interface User {
  id: string;
  email: string;
  display_name: string;
  language_pref?: string;
  status: UserStatus;
  roles: string[];
  last_login_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number; // seconds
  user: User;
}

// === Permission catalog (mirrors backend/app/auth/permissions.py) ===
export type Permission =
  | "view_doc"
  | "edit_doc_metadata"
  | "delete_doc"
  | "manage_users"
  | "manage_roles"
  | "manage_groups"
  | "manage_sources"
  | "manage_settings"
  | "invite_user"
  | "view_audit_log";

// === Query ===

export interface QueryRequest {
  question: string;
  language?: string;
  bypass_cache?: boolean;
}

export interface Citation {
  index: number;
  chunk_id: string;
  doc_id: string;
  title: string;
  section_title?: string;
  page_number?: number;
  source?: string;
  source_id?: string;
  url?: string;
  updated_at?: string;
  language?: string;
  score: number;
  snippet?: string;
}

export interface NoResultBlock {
  reason: string;
  message: string;
  suggestions: string[];
  denied_count: number;
}

export interface QueryResponse {
  query_id: string;
  answer: string;
  citations: Citation[];
  warnings: string[];
  no_answer: boolean;
  no_result: NoResultBlock | null;
  latency_ms: number;
  cache_hit: boolean;
  llm_model: string | null;
  cost_usd: number;
  status: string;
}

export interface QueryHistoryItem {
  id: string;
  query_text: string;
  query_language: string | null;
  answer_text: string | null;
  status: string;
  latency_ms: number | null;
  cost_usd: number | null;
  llm_model: string | null;
  created_at: string;
}

// === Documents ===

export type DocumentStatus = "active" | "indexing" | "stale" | "deleted";

export interface Document {
  id: string;
  title: string;
  source_id?: string;
  source_type?: string;
  language?: string;
  status: DocumentStatus;
  url?: string;
  created_at: string;
  updated_at: string;
  chunk_count?: number;
}

export interface DocumentUpdate {
  title?: string;
  language?: string;
}

export interface DocumentPreview {
  url: string;
  expires_at: string;
}

// === Sources ===

export type SourceType = "google_drive" | "notion";
export type SourceStatus = "active" | "paused" | "error";

export interface Source {
  id: string;
  name: string;
  type: SourceType;
  status: SourceStatus;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceCreate {
  name: string;
  type: SourceType;
  config: Record<string, unknown>;
}

export interface SourceUpdate {
  name?: string;
  status?: SourceStatus;
  config?: Record<string, unknown>;
}

// === Sync jobs ===

export type SyncJobStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "partial";

export interface SyncJob {
  id: string;
  source_id: string;
  status: SyncJobStatus;
  stage?: string;
  items_processed: number;
  items_added: number;
  items_updated: number;
  items_deleted: number;
  items_skipped: number;
  error_message?: string;
  started_at: string;
  finished_at?: string | null;
}

// === Users / RBAC ===

export interface UserInviteRequest {
  email: string;
  display_name: string;
  role_ids: string[];
}

export interface UserUpdate {
  display_name?: string;
  status?: UserStatus;
  role_ids?: string[];
}

export interface RoleAssignRequest {
  role_id: string;
}

// === Roles ===

export interface Role {
  id: string;
  name: string;
  description?: string;
  permissions: Permission[];
  is_static: boolean;
  user_count?: number;
  created_at: string;
  updated_at: string;
}

export interface RoleCreate {
  name: string;
  description?: string;
  permissions: Permission[];
}

export interface RoleUpdate {
  name?: string;
  description?: string;
  permissions?: Permission[];
}

// === Groups ===

export interface Group {
  id: string;
  name: string;
  description?: string;
  member_count?: number;
  document_count?: number;
  created_at: string;
  updated_at: string;
}

export interface GroupCreate {
  name: string;
  description?: string;
}

export interface GroupUpdate {
  name?: string;
  description?: string;
}

// === Settings ===

export interface SystemSettings {
  id: string;
  default_language: string;
  default_query_language: string;
  feedback_retention_days: number;
  audit_retention_days: number;
  rate_limit_query_per_minute: number;
  max_doc_size_mb: number;
  allow_signup: boolean;
  extra: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SystemSettingsUpdate {
  default_language?: string;
  default_query_language?: string;
  feedback_retention_days?: number;
  audit_retention_days?: number;
  rate_limit_query_per_minute?: number;
  max_doc_size_mb?: number;
  allow_signup?: boolean;
}

export interface AuditLogEntry {
  id: string;
  actor_id: string;
  actor_email?: string;
  action: string;
  target_type?: string;
  target_id?: string;
  ip_address?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

// === Feedback ===

export type FeedbackType = "good" | "bad" | "source_missing";

export interface FeedbackRequest {
  query_id: string;
  feedback_type: FeedbackType;
  comment?: string;
}

export interface FeedbackResponse {
  id: string;
  query_id: string;
  feedback_type: FeedbackType;
  created_at: string;
}
