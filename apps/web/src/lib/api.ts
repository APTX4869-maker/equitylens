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
  ReviewPackage,
} from "./types";

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let message = body.slice(0, 200);
    try {
      const parsed = JSON.parse(body) as { detail?: { message?: string }; error?: { message?: string } };
      message = parsed.detail?.message ?? parsed.error?.message ?? message;
    } catch { /* keep the response excerpt */ }
    throw new Error(message || `请求失败（${res.status}）`);
  }
  return res.json() as Promise<T>;
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
  onboardings: (signal?: AbortSignal) => getJson<{ items: OnboardingTask[]; next_cursor: string | null }>("/api/v1/company-onboardings?limit=200", { signal }),
  onboarding: (id: string, signal?: AbortSignal) => getJson<OnboardingTask>(`/api/v1/company-onboardings/${id}`, { signal }),
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
  provenance: (entityId: string) =>
    getJson<{ entity_id: string; kind: string; tree: ProvenanceNode }>(
      `/api/v1/provenance/${entityId}`
    ),
};
