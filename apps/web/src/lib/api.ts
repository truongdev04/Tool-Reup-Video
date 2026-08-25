/**
 * Client cho FastAPI backend (`apps/api`) — dashboard Phase 4 thật (§19),
 * gọi qua CORS vì chạy khác port `next dev` (xem `apps/api/api/main.py`).
 *
 * `NEXT_PUBLIC_API_URL` đặt trong `.env.local` nếu backend không chạy ở
 * cổng mặc định 8000 (vd. máy dev đã dùng cổng đó cho việc khác).
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Kiểu dữ liệu — khớp apps/api/api/routes/dashboard.py
// ---------------------------------------------------------------------------

export type JobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "needs_review";

export interface Project {
  id: string;
  name: string;
  target_locales: string[];
  source_video_count: number;
  job_count: number;
  jobs_by_status: Record<string, number>;
  created_at: string;
}

export interface ProjectDetail {
  id: string;
  name: string;
  target_locales: string[];
  approval_gates: Record<string, boolean>;
  source_videos: { id: string; filename: string; source_locale: string | null }[];
  jobs: {
    id: string;
    locale: string;
    status: JobStatus;
    current_stage: string | null;
    progress: number;
    source_filename: string | null;
    created_at: string;
  }[];
}

export interface QueueJob {
  id: string;
  project_id: string;
  project_name: string | null;
  locale: string;
  status: JobStatus;
  current_stage: string | null;
  progress: number;
  retry_count: number;
  priority: number;
  error_message: string | null;
  source_filename: string | null;
  created_at: string;
}

export interface DriftInfo {
  target_duration_ms: number;
  actual_duration_ms: number | null;
  fit_strategy: string;
  tempo_ratio: number;
  drift_ms: number;
  cumulative_drift_ms: number;
  needs_manual_review: boolean;
}

export interface WorkspaceUnit {
  id: string;
  idx: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  source_text: string;
  translated_text: string | null;
  translation_version: number | null;
  translation_approved_by: string | null;
  needs_transcreation: boolean;
  drift: DriftInfo | null;
  audio_url: string | null;
  audio_duration_ms: number | null;
}

export interface Gate {
  gate: string;
  is_enabled: boolean;
  approved_by: string | null;
  approved_at: string | null;
  note: string | null;
}

export interface JobWorkspace {
  id: string;
  project_id: string;
  project_name: string | null;
  locale: string;
  status: JobStatus;
  current_stage: string | null;
  progress: number;
  error_message: string | null;
  source_filename: string | null;
  units: WorkspaceUnit[];
  gates: Gate[];
  qc_verdict: string | null;
  qc_findings: { check: string; verdict: string; message: string }[];
  final_video_url: string | null;
}

export interface PipelineReport {
  job_id: string;
  locale: string;
  ok: boolean;
  total_ms: number;
  cached_count: number;
  outcomes: {
    stage: string;
    status: JobStatus;
    cached: boolean;
    duration_ms: number;
    note: string | null;
  }[];
}

export interface PublishingPlatform {
  id: string;
  name: string;
  needs_oauth_app: boolean;
  is_configured: boolean;
  quota_daily_units: number;
  cost_per_upload_units: number;
}

export interface PublishingAccount {
  id: string;
  platform: string;
  label: string;
  scopes: string[];
  is_revoked: boolean;
  expires_at: string | null;
  usable: boolean;
  connected_at: string;
}

export interface QuotaEntry {
  account_id: string;
  label: string;
  platform: string;
  used_units: number;
  limit_units: number;
  remaining_uploads: number;
}

export interface PublishingHistoryEntry {
  id: string;
  platform: string;
  account_ref: string;
  status: JobStatus;
  platform_video_id: string | null;
  published_at: string | null;
  quota_units_used: number | null;
  error_message: string | null;
  job_id?: string | null;
  locale?: string | null;
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

export const api = {
  listProjects: () => request<Project[]>("/api/dashboard/projects"),
  projectDetail: (id: string) => request<ProjectDetail>(`/api/dashboard/projects/${id}`),
  listJobs: (params?: { project_id?: string; status?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<QueueJob[]>(`/api/dashboard/jobs${qs ? `?${qs}` : ""}`);
  },
  jobWorkspace: (id: string) => request<JobWorkspace>(`/api/dashboard/jobs/${id}`),
  rerunPreview: () => request<{ stages: string[] }>("/api/dashboard/rerun-preview"),
  editUnit: (unitId: string, body: { locale: string; text: string; edited_by: string }) =>
    request<{ translation_id: string; version: number; text: string; job_id: string; will_rerun: string[] }>(
      `/api/dashboard/units/${unitId}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  rerunDownstream: (jobId: string) =>
    request<PipelineReport>(`/api/dashboard/jobs/${jobId}/rerun-downstream`, { method: "POST" }),
  approveGate: (jobId: string, gate: string, body: { approved_by: string; note?: string }) =>
    request<{ gate: string; approved_by: string; approved_at: string }>(
      `/api/dashboard/jobs/${jobId}/gates/${gate}/approve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  resumeJob: (jobId: string) =>
    request<PipelineReport>(`/api/dashboard/jobs/${jobId}/resume`, { method: "POST" }),

  listPlatforms: () => request<PublishingPlatform[]>("/api/dashboard/publishing/platforms"),
  listAccounts: () => request<PublishingAccount[]>("/api/dashboard/publishing/accounts"),
  revokeAccount: (accountId: string) =>
    request<{ id: string; is_revoked: boolean }>(
      `/api/dashboard/publishing/accounts/${accountId}/revoke`, { method: "POST" },
    ),
  quotaSummary: () => request<QuotaEntry[]>("/api/dashboard/publishing/quota"),
  publishingHistory: () => request<PublishingHistoryEntry[]>("/api/dashboard/publishing/history"),
  jobPublishing: (jobId: string) =>
    request<{ history: PublishingHistoryEntry[]; quota: QuotaEntry[] }>(
      `/api/dashboard/jobs/${jobId}/publishing`,
    ),
  publishJob: (
    jobId: string,
    body: { platform: string; account_id: string; title: string; description?: string; hashtags?: string[] },
  ) => request<PipelineReport>(`/api/dashboard/jobs/${jobId}/publish`, {
    method: "POST", body: JSON.stringify(body),
  }),
  authorizeUrl: (platform: string, label: string) =>
    `${BASE_URL}/api/dashboard/publishing/authorize?${new URLSearchParams({ platform, label })}`,
};

export function apiBaseUrl(): string {
  return BASE_URL;
}
