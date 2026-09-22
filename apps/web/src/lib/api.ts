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

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let detail: ApiErrorDetail = { message: body.slice(0, 200) };
    try {
      const parsed = JSON.parse(body) as { detail?: ApiErrorDetail; error?: ApiErrorDetail };
      detail = parsed.detail ?? parsed.error ?? detail;
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

function identityQuery(identity?: { security_id?: string; publication_id?: string | null }) {
  const params = new URLSearchParams();
  if (identity?.security_id) params.set("security_id", identity.security_id);
  if (identity?.publication_id) params.set("publication_id", identity.publication_id);
  return params.size ? `?${params}` : "";
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
  company: (ticker: string, identity?: { security_id?: string; publication_id?: string | null }, signal?: AbortSignal) =>
    getJson<CompanyInfo>(`/api/v1/companies/${ticker}${identityQuery(identity)}`, { signal }),
  facts: (ticker: string, metrics: string[], frequency = "quarterly", limit?: number) =>
    getJson<FactsResponse>(
      `/api/v1/companies/${ticker}/facts?metrics=${encodeURIComponent(
        metrics.join(",")
      )}&frequency=${frequency}${limit ? `&limit=${limit}` : ""}`
    ),
  metrics: (ticker: string, metrics: string[], frequency = "quarterly", limit?: number) =>
    getJson<MetricsResponse>(
      `/api/v1/companies/${ticker}/metrics?metrics=${encodeURIComponent(
        metrics.join(",")
      )}&frequency=${frequency}${limit ? `&limit=${limit}` : ""}`
    ),
  overview: (ticker: string, identity?: { security_id?: string; publication_id?: string | null }, signal?: AbortSignal) =>
    getJson<OverviewResponse>(`/api/v1/companies/${ticker}/overview${identityQuery(identity)}`, { signal }),
  marketQuote: (ticker: string, identity?: { security_id?: string; publication_id?: string | null }, signal?: AbortSignal) =>
    getJson<MarketQuote>(`/api/v1/companies/${ticker}/market/quote${identityQuery(identity)}`, { signal }),
  provenance: (entityId: string, publicationId?: string | null) =>
    getJson<{ entity_id: string; kind: string; tree: ProvenanceNode }>(
      `/api/v1/provenance/${entityId}${publicationId ? `?publication_id=${encodeURIComponent(publicationId)}` : ""}`
    ),
};
