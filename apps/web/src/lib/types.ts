export type CompanyInfo = {
  company_id?: string;
  security_id?: string;
  publication_id?: string | null;
  ticker: string;
  cik: string;
  name: string;
  exchange: string | null;
  fiscal_year_end: string | null;
  sic_description?: string | null;
  website?: string | null;
  source_freshness: Record<string, { fetched_at: string; sha256: string }>;
};

export type CompanyCapability = {
  module: string;
  status: string;
  reason: string | null;
  coverage?: Record<string, unknown> | null;
};

export type CompanyListItem = {
  company_id: string;
  security_id: string;
  ticker: string;
  name: string;
  exchange: string | null;
  publication_id: string | null;
  quality_status: string;
  capabilities: CompanyCapability[];
};

export type DiscoveryCandidate = {
  candidate_id: string;
  company_id: string;
  legal_name: string;
  ticker: string;
  exchange: string;
  class_label?: string | null;
  currency: string;
  instrument_type: string;
  evidence: Record<string, unknown>[];
};

export type DiscoveryResult = {
  discovery_id: string;
  ticker: string;
  identity_hash: string;
  expires_at: string;
  candidates: DiscoveryCandidate[];
  eligibility: { status: string; reason_code?: string | null; reason?: string | null; template?: string | null };
  coverage: { form_counts: Record<string, number>; earliest_report_date?: string | null; latest_report_date?: string | null };
  evidence: Record<string, unknown>[];
};

export type QualityCheck = {
  check_id: string;
  scope_key: string;
  status: string;
  severity: string;
  reason?: string | null;
  actual?: unknown;
  expected?: unknown;
  evidence?: unknown;
};

export type OnboardingProgressStage = {
  id: "IDENTITY" | "FETCH" | "ADAPTATION" | "BUILD_VALIDATE" | "REVIEW_PUBLISH";
  label: string;
  status: "COMPLETED" | "CURRENT" | "UPCOMING";
  activity: "QUEUED" | "RUNNING" | "WAITING_FOR_MAINTAINER" | "FAILED" | "CANCELLED" | "COMPLETED" | null;
  started_at: string | null;
  completed_at: string | null;
};

export type OnboardingProgress = {
  completed: number;
  total: 5;
  percent: number;
  current_stage: OnboardingProgressStage["id"];
  activity: Exclude<OnboardingProgressStage["activity"], null>;
  actor: "SYSTEM" | "MAINTAINER" | "NONE";
  updated_at: string;
  stalled: boolean;
  stages: OnboardingProgressStage[];
  fingerprint: string;
};

export type ProfileCandidate = {
  profile_candidate_id: string;
  onboarding_id: string;
  task_revision: number;
  fetch_bundle_id?: string;
  input_sha256?: string;
  content_sha256: string;
  snapshot_manifest: Record<string, unknown>[];
  profile: Record<string, unknown>;
  unresolved_fields: { path: string; reason: string; action: string }[];
  review_status: "NEEDS_ADAPTATION";
  created_at: string;
  current: boolean;
};

export type OnboardingTask = {
  onboarding_id: string;
  company_id: string;
  ticker?: string;
  company_name?: string;
  state: string;
  current_step: string | null;
  revision: number;
  cancel_requested: boolean;
  input_fingerprint: string;
  discovery_id?: string | null;
  fetch_bundle_id?: string | null;
  profile_candidate_id?: string | null;
  profile_id?: string | null;
  dataset_id?: string | null;
  quality_report_id?: string | null;
  review_id?: string | null;
  publication_id?: string | null;
  error?: { code?: string; message?: string; [key: string]: unknown } | null;
  created_at: string;
  updated_at: string;
  actions: string[];
  progress?: OnboardingProgress;
  steps?: Record<string, unknown>[];
  checks?: QualityCheck[];
  blocking_reasons?: { check_id: string; reason?: string | null }[];
};

export type ReviewPackage = {
  onboarding_id: string;
  company_id: string;
  revision: number;
  fingerprint: string;
  dataset_id: string;
  dataset_hash: string;
  profile_id: string;
  profile_hash: string;
  profile: Record<string, unknown>;
  source_manifest: Record<string, unknown>;
  quality: { result: string; checks: QualityCheck[]; [key: string]: unknown };
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
  result_id?: string | null;
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
  result_id?: string | null;
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
    {
      metric?: string;
      value?: number | null;
      unit?: string | null;
      period?: string | null;
      frequency?: string | null;
      status?: string | null;
      formula_id?: string | null;
      formula_version?: string | null;
      canonical_fact_id?: string | null;
      result_id?: string | null;
      input_fact_ids?: string[];
      fiscal_year?: number | null;
      fiscal_quarter?: number | null;
      period_end?: string | null;
      missing_reason?: string | null;
    }
  >;
  trend: Record<string, { label: string; unit?: string | null; values: (number | null)[]; periods: (string | null)[] }>;
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
