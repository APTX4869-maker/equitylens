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

CREATE TABLE IF NOT EXISTS schema_migration (
  version INTEGER PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL,
  checksum VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS issuer_profile_version (
  profile_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  version INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  content_json JSON NOT NULL,
  content_sha256 VARCHAR NOT NULL,
  created_at TIMESTAMP NOT NULL,
  UNIQUE(company_id, version)
);

CREATE TABLE IF NOT EXISTS dataset_version (
  dataset_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  profile_id VARCHAR NOT NULL REFERENCES issuer_profile_version(profile_id),
  source_manifest_json JSON NOT NULL,
  parser_version VARCHAR NOT NULL,
  rule_version VARCHAR NOT NULL,
  dataset_hash VARCHAR NOT NULL,
  state VARCHAR NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_row (
  dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
  entity_type VARCHAR NOT NULL,
  row_id VARCHAR NOT NULL,
  payload_json JSON NOT NULL,
  payload_sha256 VARCHAR NOT NULL,
  PRIMARY KEY(dataset_id, entity_type, row_id)
);

CREATE TABLE IF NOT EXISTS quality_report (
  report_id VARCHAR PRIMARY KEY,
  dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
  rule_version VARCHAR NOT NULL,
  result VARCHAR NOT NULL,
  fingerprint VARCHAR NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS company_quality_check (
  report_id VARCHAR NOT NULL REFERENCES quality_report(report_id),
  check_id VARCHAR NOT NULL,
  scope_key VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  severity VARCHAR NOT NULL,
  actual_json JSON,
  expected_json JSON,
  tolerance_json JSON,
  evidence_json JSON,
  reason VARCHAR,
  PRIMARY KEY(report_id, check_id, scope_key)
);

CREATE TABLE IF NOT EXISTS adaptation_review (
  review_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  fingerprint VARCHAR NOT NULL,
  reviewer VARCHAR NOT NULL,
  decision VARCHAR NOT NULL,
  note VARCHAR,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS publication (
  publication_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  dataset_id VARCHAR NOT NULL REFERENCES dataset_version(dataset_id),
  profile_id VARCHAR NOT NULL REFERENCES issuer_profile_version(profile_id),
  quality_report_id VARCHAR,
  review_id VARCHAR,
  fingerprint VARCHAR NOT NULL,
  published_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS company_capability (
  publication_id VARCHAR NOT NULL REFERENCES publication(publication_id),
  module VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  reason VARCHAR,
  coverage_json JSON,
  PRIMARY KEY(publication_id, module)
);

CREATE INDEX IF NOT EXISTS dataset_company_idx ON dataset_version(company_id);
CREATE INDEX IF NOT EXISTS publication_company_idx ON publication(company_id, published_at);

CREATE TABLE IF NOT EXISTS company_onboarding (
  onboarding_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL REFERENCES company(company_id),
  state VARCHAR NOT NULL,
  current_step VARCHAR,
  revision INTEGER NOT NULL,
  cancel_requested BOOLEAN NOT NULL,
  input_fingerprint VARCHAR NOT NULL,
  discovery_id VARCHAR,
  profile_id VARCHAR,
  dataset_id VARCHAR,
  quality_report_id VARCHAR,
  review_id VARCHAR,
  publication_id VARCHAR,
  error_json JSON,
  next_attempt_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_security (
  onboarding_id VARCHAR NOT NULL,
  security_id VARCHAR NOT NULL REFERENCES security(security_id),
  PRIMARY KEY(onboarding_id, security_id)
);

CREATE TABLE IF NOT EXISTS onboarding_step_attempt (
  attempt_id VARCHAR PRIMARY KEY,
  onboarding_id VARCHAR NOT NULL,
  step VARCHAR NOT NULL,
  attempt_no INTEGER NOT NULL,
  input_hash VARCHAR NOT NULL,
  output_hash VARCHAR,
  state VARCHAR NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  heartbeat_at TIMESTAMP,
  error_json JSON,
  UNIQUE(onboarding_id, step, attempt_no)
);

CREATE TABLE IF NOT EXISTS api_idempotency (
  key VARCHAR PRIMARY KEY,
  request_hash VARCHAR NOT NULL,
  response_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS onboarding_company_idx ON company_onboarding(company_id, state);
CREATE INDEX IF NOT EXISTS onboarding_runnable_idx ON company_onboarding(state, next_attempt_at);

CREATE TABLE IF NOT EXISTS company_discovery (
  discovery_id VARCHAR PRIMARY KEY,
  ticker VARCHAR NOT NULL,
  identity_hash VARCHAR NOT NULL,
  payload_json JSON NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS discovery_ticker_idx ON company_discovery(ticker, expires_at);

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
  security_id VARCHAR,
  publication_id VARCHAR,
  name VARCHAR NOT NULL,
  model_name VARCHAR NOT NULL,
  model_version VARCHAR,
  assumptions_json JSON NOT NULL,
  assumptions_hash VARCHAR,
  confirmation_fingerprint VARCHAR,
  status VARCHAR,
  confirmed_at TIMESTAMP,
  source_metadata_json JSON,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS valuation_run (
  valuation_run_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  security_id VARCHAR,
  publication_id VARCHAR,
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
  model_quality_json JSON,
  confirmation_fingerprint VARCHAR
);

CREATE TABLE IF NOT EXISTS valuation_plan (
  plan_id VARCHAR PRIMARY KEY,
  company_id VARCHAR NOT NULL,
  security_id VARCHAR,
  publication_id VARCHAR,
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
