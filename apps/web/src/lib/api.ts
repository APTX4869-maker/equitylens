import type {
  CompanyInfo,
  CompanyListItem,
  DiscoveryResult,
  FactsResponse,
  MarketQuote,
  MetricsResponse,
  OverviewResponse,
  ProvenanceNode,
  OnboardingTask,
  ProfileCandidate,
  ReviewPackage,
  ResearchIdentity,
} from "./types";

export type ApiErrorDetail = {
  code?: string;
  message?: string;
  remediation?: string;
  field_errors?: { path: string; message: string }[];
};

export class ApiRequestError extends Error {
  constructor(public status: number, public detail: ApiErrorDetail) {
    super(detail.message || `请求失败（${status}）`);
  }
}

export type ValuationPlan = {
  plan_id: string;
  name: string;
  valuation_run_id: string | null;
  scenario_key: "base" | "bear" | "bull" | null;
  reference_value: number | null;
  reference_price: number | null;
  reference_price_reason?: string | null;
  margin_of_safety: number;
  notes?: string | null;
  conditions_to_verify: string[];
  parent_plan_id?: string | null;
  version: number | null;
  review_status: string;
  review_reason?: string | null;
  assumptions_json?: Record<string, unknown>;
  archived_at?: string | null;
  created_at?: string;
};

export type ValuationPlanCopyDraft = {
  parent_plan_id: string;
  next_version: number;
  assumptions: Record<string, unknown>;
  source_plan: ValuationPlan;
  plan_defaults: {
    scenario_key: "base" | "bear" | "bull";
    margin_of_safety: number;
    name: string;
    notes?: string | null;
    conditions_to_verify: string[];
  };
};

export type ValuationPlanComparison = {
  plans: ValuationPlan[];
  fields: {
    key: string;
    label: string;
    values: { plan_id: string; value: unknown }[];
    changed: boolean;
  }[];
  changed_fields: string[];
  has_differences: boolean;
};

export type ValuationRunSnapshot = {
  valuation_run_id: string;
  status: string;
  model_name: string;
  model_version: string;
  run_at: string;
  assumptions: { inputs?: Record<string, unknown>; meta?: Record<string, unknown> };
  output: Record<string, unknown>;
  scenarios?: Record<string, unknown> | null;
  warnings?: string[];
};

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let detail: ApiErrorDetail = { message: body.slice(0, 200) };
    try {
      const parsed = JSON.parse(body) as { detail?: ApiErrorDetail | string; error?: ApiErrorDetail | string };
      const parsedDetail = parsed.detail ?? parsed.error;
      detail = typeof parsedDetail === "string" ? { message: parsedDetail } : parsedDetail ?? detail;
    } catch { /* keep the response excerpt */ }
    throw new ApiRequestError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function userErrorMessage(reason: unknown): string {
  if (reason instanceof Error) return reason.message;
  if (typeof reason === "string") return reason.replace(/^Error:\s*/, "");
  return "请求未完成";
}

function longRunningApiPath(path: string): string {
  const configured = process.env.NEXT_PUBLIC_EQUITYLENS_API_URL?.replace(/\/$/, "");
  if (configured) return `${configured}${path}`;
  if (
    typeof window !== "undefined" &&
    window.location.port === "3000" &&
    ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ) {
    return `http://127.0.0.1:8000${path}`;
  }
  return path;
}

function identityQuery(identity?: ResearchIdentity) {
  const params = new URLSearchParams();
  if (identity?.security_id) params.set("security_id", identity.security_id);
  if (identity?.publication_id) params.set("publication_id", identity.publication_id);
  return params.size ? `?${params}` : "";
}

function planListQuery(options: {
  status?: "active" | "archived";
  q?: string;
  limit?: number;
  cursor?: string | null;
}) {
  const params = new URLSearchParams();
  params.set("status", options.status ?? "active");
  params.set("limit", String(options.limit ?? 6));
  if (options.q?.trim()) params.set("q", options.q.trim());
  if (options.cursor) params.set("cursor", options.cursor);
  return params.toString();
}

export const api = {
  fetchJson: <T>(path: string, init?: RequestInit): Promise<T> => getJson<T>(path, init),
  fetchLongRunningJson: <T>(path: string, init?: RequestInit): Promise<T> =>
    getJson<T>(longRunningApiPath(path), init),
  companies: (signal?: AbortSignal) => getJson<{ items: CompanyListItem[]; next_cursor: string | null }>("/api/v1/companies?limit=200", { signal }),
  discoverCompany: (ticker: string, signal?: AbortSignal) => getJson<DiscoveryResult>("/api/v1/companies/discover", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker }), signal,
  }),
  createOnboarding: (discovery: DiscoveryResult, candidateId: string, idempotencyKey: string) =>
    getJson<OnboardingTask>("/api/v1/company-onboardings", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ discovery_id: discovery.discovery_id, identity_hash: discovery.identity_hash, candidate_id: candidateId }),
    }),
  onboardings: (signal?: AbortSignal, attentionOnly = false) => getJson<{ items: OnboardingTask[]; next_cursor: string | null; attention_count: number }>(`/api/v1/company-onboardings?limit=200${attentionOnly ? "&attention_only=true" : ""}`, { signal }),
  onboarding: (id: string, signal?: AbortSignal) => getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}`, { signal }),
  profileCandidate: (id: string, signal?: AbortSignal) => getJson<ProfileCandidate>(`/api/v1/company-onboardings/${id}/profile-candidate`, { signal }),
  importProfileYaml: (id: string, revision: number, yamlText: string, idempotencyKey: string) =>
    getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}/profile-yaml`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_revision: revision, yaml_text: yamlText }),
    }),
  refetchOnboarding: (id: string, revision: number) =>
    getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}/refetch`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: revision }),
    }),
  reviewPackage: (id: string, signal?: AbortSignal) => getJson<ReviewPackage>(`/api/v1/company-onboardings/${id}/review-package`, { signal }),
  reviewOnboarding: (id: string, body: { expected_revision: number; fingerprint: string; decision: "APPROVE" | "REJECT"; reviewer: string; note: string }) =>
    getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  reviseOnboarding: (id: string, action: "retry" | "cancel", revision: number) =>
    getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision }) }),
  company: (ticker: string, identity?: ResearchIdentity, signal?: AbortSignal) =>
    getJson<CompanyInfo>(`/api/v1/companies/${ticker}${identityQuery(identity)}`, { signal }),
  facts: (ticker: string, metrics: string[], frequency = "quarterly", limit?: number, identity?: ResearchIdentity) =>
    getJson<FactsResponse>(
      `/api/v1/companies/${ticker}/facts?metrics=${encodeURIComponent(
        metrics.join(",")
      )}&frequency=${frequency}${limit ? `&limit=${limit}` : ""}${identityQuery(identity).replace("?", "&")}`
    ),
  metrics: (ticker: string, metrics: string[], frequency = "quarterly", limit?: number, identity?: ResearchIdentity) =>
    getJson<MetricsResponse>(
      `/api/v1/companies/${ticker}/metrics?metrics=${encodeURIComponent(
        metrics.join(",")
      )}&frequency=${frequency}${limit ? `&limit=${limit}` : ""}${identityQuery(identity).replace("?", "&")}`
    ),
  overview: (ticker: string, identity?: ResearchIdentity, signal?: AbortSignal) =>
    getJson<OverviewResponse>(`/api/v1/companies/${ticker}/overview${identityQuery(identity)}`, { signal }),
  marketQuote: (ticker: string, identity?: ResearchIdentity, signal?: AbortSignal) =>
    getJson<MarketQuote>(`/api/v1/companies/${ticker}/market/quote${identityQuery(identity)}`, { signal }),
  valuationPlans: (
    ticker: string,
    options: { status?: "active" | "archived"; q?: string; limit?: number; cursor?: string | null },
    signal?: AbortSignal,
  ) => getJson<{ plans: ValuationPlan[]; next_cursor: string | null }>(
    `/api/v1/companies/${ticker}/valuation/plans?${planListQuery(options)}`,
    { signal },
  ),
  valuationPlan: (ticker: string, planId: string) =>
    getJson<ValuationPlan>(`/api/v1/companies/${ticker}/valuation/plans/${planId}`),
  valuationRunSnapshot: (ticker: string, runId: string) =>
    getJson<ValuationRunSnapshot>(`/api/v1/companies/${ticker}/valuation/runs/${runId}`),
  archiveValuationPlan: (ticker: string, planId: string) =>
    getJson<ValuationPlan>(`/api/v1/companies/${ticker}/valuation/plans/${planId}/archive`, { method: "POST" }),
  restoreValuationPlan: (ticker: string, planId: string) =>
    getJson<ValuationPlan>(`/api/v1/companies/${ticker}/valuation/plans/${planId}/restore`, { method: "POST" }),
  copyValuationPlan: (ticker: string, planId: string) =>
    getJson<ValuationPlanCopyDraft>(`/api/v1/companies/${ticker}/valuation/plans/${planId}/copy`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }),
  compareValuationPlans: (ticker: string, planIds: string[]) =>
    getJson<ValuationPlanComparison>(
      `/api/v1/companies/${ticker}/valuation/plans/compare?ids=${encodeURIComponent(planIds.join(","))}`
    ),
  createValuationPlan: (ticker: string, body: Record<string, unknown>, idempotencyKey: string) =>
    getJson<ValuationPlan>(`/api/v1/companies/${ticker}/valuation/plans`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    }),
  segments: <T>(ticker: string, kind: "segment" | "product", frequency: "annual" | "quarterly", identity: ResearchIdentity) =>
    getJson<T>(`/api/v1/companies/${ticker}/segments?kind=${kind}&frequency=${frequency}${identityQuery(identity).replace("?", "&")}`),
  moat: <T>(ticker: string, identity: ResearchIdentity) =>
    getJson<T>(`/api/v1/companies/${ticker}/moat${identityQuery(identity)}`),
  risks: <T>(ticker: string, identity: ResearchIdentity) =>
    getJson<T>(`/api/v1/companies/${ticker}/risks${identityQuery(identity)}`),
  management: <T>(ticker: string, identity: ResearchIdentity) =>
    getJson<T>(`/api/v1/companies/${ticker}/management${identityQuery(identity)}`),
  promises: <T>(ticker: string, identity: ResearchIdentity) =>
    getJson<T>(`/api/v1/companies/${ticker}/promises${identityQuery(identity)}`),
  askResearch: <T>(ticker: string, question: string, identity: ResearchIdentity) =>
    getJson<T>("/api/v1/research/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, question, ...identity }),
    }),
  provenance: (entityId: string, publicationId?: string | null) =>
    getJson<{ entity_id: string; kind: string; tree: ProvenanceNode }>(
      `/api/v1/provenance/${entityId}${publicationId ? `?publication_id=${encodeURIComponent(publicationId)}` : ""}`
    ),
};
