import type {
  CompanyInfo,
  FactsResponse,
  MarketQuote,
  MetricsResponse,
  OverviewResponse,
  ProvenanceNode,
} from "./types";

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status} ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  fetchJson: <T>(path: string, init?: RequestInit): Promise<T> => getJson<T>(path, init),
  company: (ticker: string) => getJson<CompanyInfo>(`/api/v1/companies/${ticker}`),
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
  overview: (ticker: string) => getJson<OverviewResponse>(`/api/v1/companies/${ticker}/overview`),
  marketQuote: (ticker: string) =>
    getJson<MarketQuote>(`/api/v1/companies/${ticker}/market/quote`),
  provenance: (entityId: string) =>
    getJson<{ entity_id: string; kind: string; tree: ProvenanceNode }>(
      `/api/v1/provenance/${entityId}`
    ),
};
