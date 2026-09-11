-- EquityLens initial logical schema (DuckDB-friendly SQL)

CREATE TABLE IF NOT EXISTS company (
  company_id VARCHAR PRIMARY KEY,
  ticker VARCHAR NOT NULL,
  cik VARCHAR,
  legal_name VARCHAR,
  fiscal_year_end VARCHAR,
  exchange VARCHAR,
  reporting_template VARCHAR,
  active_publication_id VARCHAR,
  quality_status VARCHAR,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS company_cik_unique ON company(cik);

CREATE TABLE IF NOT EXISTS security (
  security_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  class_label VARCHAR,
  exchange VARCHAR NOT NULL,
  currency VARCHAR NOT NULL,
  instrument_type VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  identity_evidence_json JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS security_ticker_alias (
  alias_id VARCHAR PRIMARY KEY,
  security_id VARCHAR NOT NULL REFERENCES security(security_id),
  ticker VARCHAR NOT NULL,
  exchange VARCHAR NOT NULL,
  valid_from DATE NOT NULL,
  valid_to DATE
);

CREATE INDEX IF NOT EXISTS security_company_idx ON security(company_id);
CREATE INDEX IF NOT EXISTS security_alias_lookup_idx ON security_ticker_alias(ticker, exchange);

CREATE TABLE IF NOT EXISTS source_document (
  source_document_id VARCHAR PRIMARY KEY,
  company_id VARCHAR,
  provider VARCHAR NOT NULL,
  document_type VARCHAR NOT NULL,
  form_type VARCHAR,
  accession_number VARCHAR,
  published_at TIMESTAMP,
  filed_at TIMESTAMP,
  source_url VARCHAR NOT NULL,
  fetched_at TIMESTAMP NOT NULL,
  content_sha256 VARCHAR NOT NULL,
  local_path VARCHAR,
  parser_version VARCHAR,
  metadata_json JSON
);

CREATE TABLE IF NOT EXISTS raw_fact (
  raw_fact_id VARCHAR PRIMARY KEY,
  source_document_id VARCHAR NOT NULL,
  taxonomy VARCHAR,
  concept VARCHAR NOT NULL,
  unit VARCHAR,
  raw_value DOUBLE,
  start_date DATE,
  end_date DATE,
  instant_date DATE,
  context_id VARCHAR,
  dimensions_json JSON,
  fiscal_year INTEGER,
  fiscal_period VARCHAR,
  frame VARCHAR,
  raw_json JSON
);

CREATE TABLE IF NOT EXISTS canonical_fact (
  canonical_fact_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  canonical_metric VARCHAR NOT NULL,
  period_type VARCHAR NOT NULL,
  fiscal_year INTEGER,
  fiscal_quarter INTEGER,
  period_start DATE,
  period_end DATE,
  instant_date DATE,
  value DOUBLE,
  unit VARCHAR,
  status VARCHAR NOT NULL,
  mapping_rule_id VARCHAR NOT NULL,
  mapping_version VARCHAR NOT NULL,
  source_raw_fact_ids JSON NOT NULL,
  as_known_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  warnings_json JSON
);

CREATE TABLE IF NOT EXISTS metric_value (
  metric_value_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  metric_name VARCHAR NOT NULL,
  period_label VARCHAR,
  period_end DATE,
  value DOUBLE,
  unit VARCHAR,
  status VARCHAR NOT NULL,
  formula_id VARCHAR NOT NULL,
  formula_version VARCHAR NOT NULL,
  input_fact_ids JSON NOT NULL,
  calculated_at TIMESTAMP NOT NULL,
  warnings_json JSON
);

CREATE TABLE IF NOT EXISTS evidence_span (
  evidence_id VARCHAR PRIMARY KEY,
  source_document_id VARCHAR NOT NULL,
  section_title VARCHAR,
  page_or_locator VARCHAR,
  paragraph_index INTEGER,
  char_start INTEGER,
  char_end INTEGER,
  start_timestamp_seconds DOUBLE,
  end_timestamp_seconds DOUBLE,
  text_excerpt VARCHAR,
  extraction_method VARCHAR,
  confidence VARCHAR
);

CREATE TABLE IF NOT EXISTS segment_fact (
  segment_fact_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  segment_name_reported VARCHAR NOT NULL,
  segment_name_canonical VARCHAR,
  metric_name VARCHAR NOT NULL,
  fiscal_year INTEGER,
  fiscal_quarter INTEGER,
  period_start DATE,
  period_end DATE,
  value DOUBLE,
  unit VARCHAR,
  status VARCHAR NOT NULL,
  source_raw_fact_ids JSON,
  source_document_id VARCHAR,
  disclosure_level VARCHAR
);

CREATE TABLE IF NOT EXISTS management_promise (
  promise_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  source_evidence_id VARCHAR NOT NULL,
  speaker VARCHAR,
  statement_date DATE NOT NULL,
  promise_text VARCHAR NOT NULL,
  normalized_claim VARCHAR,
  verification_metrics JSON,
  verification_deadline DATE,
  status VARCHAR NOT NULL,
  review_evidence_ids JSON,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS market_observation (
  market_observation_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  provider VARCHAR NOT NULL,
  observed_at TIMESTAMP NOT NULL,
  price DOUBLE,
  currency VARCHAR,
  adjusted BOOLEAN,
  metadata_json JSON
);

CREATE TABLE IF NOT EXISTS valuation_assumption_set (
  assumption_set_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  model_name VARCHAR NOT NULL,
  assumptions_json JSON NOT NULL,
  source_metadata_json JSON,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS valuation_run (
  valuation_run_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  model_name VARCHAR NOT NULL,
  model_version VARCHAR NOT NULL,
  run_at TIMESTAMP NOT NULL,
  market_observation_id VARCHAR,
  assumption_set_id VARCHAR NOT NULL,
  fact_snapshot_json JSON NOT NULL,
  output_json JSON NOT NULL,
  warnings_json JSON,
  input_fingerprint VARCHAR,
  scenarios_json JSON,
  sensitivity_json JSON,
  model_quality_json JSON
);

CREATE TABLE IF NOT EXISTS valuation_plan (
  plan_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  ticker VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  reference_value DOUBLE,
  reference_source VARCHAR,
  margin_of_safety DOUBLE,
  reference_price DOUBLE,
  reference_price_reason VARCHAR,
  notes VARCHAR,
  assumptions_json JSON,
  valuation_run_id VARCHAR,
  scenario_key VARCHAR,
  source_input_fingerprint VARCHAR,
  conditions_json JSON,
  parent_plan_id VARCHAR,
  version INTEGER,
  review_status VARCHAR,
  review_reason VARCHAR,
  source_filing_as_of TIMESTAMP,
  source_quote_observed_at VARCHAR,
  created_at TIMESTAMP NOT NULL
);
