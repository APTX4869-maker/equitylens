export type CompanyInfo = {
  ticker: string;
  cik: string;
  name: string;
  exchange: string | null;
  fiscal_year_end: string | null;
  sic_description?: string | null;
  website?: string | null;
  source_freshness: Record<string, { fetched_at: string; sha256: string }>;
};

export type Fact = {
  metric: string;
  period: string;
  period_type: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  period_start: string | null;
  period_end: string | null;
  instant_date: string | null;
  value: number;
  unit: string;
  status: string;
  canonical_fact_id: string | null;
  provenance: {
    source_document_id?: string | null;
    provider?: string | null;
    form_type?: string | null;
    accession_number?: string | null;
    filed_at?: string | null;
    fetched_at?: string | null;
    source_url?: string | null;
    concept?: string | null;
    unit?: string | null;
    mapping_version?: string | null;
    formula_id?: string | null;
    status?: string | null;
  };
  input_fact_ids: string[];
};

export type FactsResponse = {
  ticker: string;
  frequency: string;
  view: string;
  facts: Fact[];
};

export type MetricPoint = {
  metric: string;
  period: string;
  value: number | null;
  unit: string | null;
  status: string | null;
  formula_id: string | null;
  formula_version: string | null;
  input_fact_ids: string[];
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  period_end: string | null;
};

export type MetricsResponse = {
  ticker: string;
  frequency: string;
  metrics: MetricPoint[];
};

export type ProvenanceNode = {
  entity_id: string;
  kind: string;
  label: string | null;
  fields: Record<string, unknown>;
  parents: ProvenanceNode[];
};

export type OverviewResponse = {
  ticker: string;
  latest_period: {
    fiscal_year: number;
    fiscal_quarter: number;
    period_end: string;
  } | null;
  kpis: Record<
    string,
    { value?: number | null; unit?: string; period?: string | null; periods?: string[] }
  >;
  trend: Record<string, { label: string; values: (number | null)[]; periods: (string | null)[] }>;
  provenance_available: boolean;
};

/** M8: latest synced market quote + deterministic derived facts. */
export type MarketQuote = {
  status: "OK" | "STALE" | "UNAVAILABLE";
  stale?: boolean;
  stale_reason?: string | null;
  quote_age_days?: number | null;
  configured: boolean;
  synced: boolean;
  reason?: string;
  quote?: {
    price: number;
    currency: string;
    observed_at: string;
    provider: string;
    provider_label: string;
    name?: string | null;
    prev_close?: number | null;
    source_label: string;
    source_url: string;
    fetched_at: string;
  };
  derived?: {
    market_cap?: number;
    pe_ttm?: number | null;
    pe_ttm_formula?: string;
    pe_ttm_reason?: string;
    pfcf_ttm?: number | null;
    fcf_yield_ttm?: number | null;
    pfcf_ttm_formula?: string;
    fcf_yield_ttm_formula?: string;
    pfcf_ttm_reason?: string;
    price_vs_fair_pct?: number;
    price_vs_fair_formula?: string;
    fair_value_per_share?: number;
  };
};
