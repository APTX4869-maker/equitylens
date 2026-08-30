"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CompanyInfo, Fact, OverviewResponse } from "@/lib/types";
import { Sidebar, Topbar, Hero, TABS, type TabKey } from "@/components/Shell";
import { OverviewSection } from "@/components/sections/OverviewSection";
import { FinancialsSection } from "@/components/sections/FinancialsSection";
import {
  BusinessSection,
  MoatSection,
  ManagementSection,
  ValuationSection,
  RisksSection,
  AiSection,
} from "@/components/sections/DemoSections";
import { MetricDrawer } from "@/components/MetricDrawer";
import { SourceDrawer } from "@/components/SourceDrawer";

export default function Home() {
  const [company, setCompany] = useState("AAPL");
  const [mode, setMode] = useState<"beginner" | "pro">("beginner");
  const [tab, setTab] = useState<TabKey>("overview");
  const [companyInfo, setCompanyInfo] = useState<CompanyInfo | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metricKey, setMetricKey] = useState<string | null>(null);
  const [metricFact, setMetricFact] = useState<Fact | null>(null);
  const [sourceEntity, setSourceEntity] = useState<string | null>(null);

  useEffect(() => {
    document.body.classList.toggle("pro", mode === "pro");
  }, [mode]);

  const load = useCallback(async () => {
    setError(null);
    setOverview(null);
    setCompanyInfo(null);
    try {
      const [c, o] = await Promise.all([api.company(company), api.overview(company)]);
      setCompanyInfo(c);
      setOverview(o);
    } catch (e) {
      setError(String(e));
    }
  }, [company]);

  useEffect(() => {
    load();
  }, [load]);

  const openMetric = useCallback((key: string, fact: Fact | null) => {
    setMetricKey(key);
    setMetricFact(fact);
  }, []);

  const openSource = useCallback((entityId: string) => {
    setSourceEntity(entityId);
  }, []);

  const realDataTabs: TabKey[] = ["overview", "financials"];

  return (
    <div className="app">
      <Sidebar company={company} tab={tab} onCompany={setCompany} onTab={setTab} />
      <main>
        <Topbar mode={mode} onMode={setMode} realData={realDataTabs.includes(tab)} />
        <div className="content">
          <Hero company={companyInfo} />
          <div className="research-toolbar">
            <div className="tool-left">
              <div className="tool-group">
                <span className="tool-label">数据源</span>
                <span className="tool-value">
                  {companyInfo?.source_freshness?.COMPANYFACTS_SNAPSHOT
                    ? `SEC EDGAR · 抓取于 ${companyInfo.source_freshness.COMPANYFACTS_SNAPSHOT.fetched_at.slice(0, 10)}`
                    : "SEC EDGAR"}
                </span>
              </div>
              <div className="tool-group">
                <span className="fresh-dot" />
                <span className="tool-label">最新财报期</span>
                <span className="tool-value">
                  {overview?.latest_period ? `FY${overview.latest_period.fiscal_year} Q${overview.latest_period.fiscal_quarter}` : "—"}
                </span>
              </div>
              <div className="tool-group">
                <span className="tool-label">视图</span>
                <span className="tool-value">最近 8-12 季</span>
              </div>
            </div>
            <div className="tool-right">
              <button className="tool-chip" onClick={() => setTab("ai")}>✦ 问 AI</button>
            </div>
          </div>

          {tab === "overview" ? (
            <section className="section active" id="section-overview">
              <OverviewSection
                company={companyInfo}
                overview={overview}
                error={error}
                onRetry={load}
                onOpenMetric={openMetric}
                onGotoTab={setTab}
              />
            </section>
          ) : null}
          {tab === "business" ? (
            <section className="section active" id="section-business">
              <BusinessSection ticker={company} />
            </section>
          ) : null}
          {tab === "financials" ? (
            <section className="section active" id="section-financials">
              <FinancialsSection ticker={company} onOpenMetric={openMetric} />
            </section>
          ) : null}
          {tab === "moat" ? (
            <section className="section active" id="section-moat">
              <MoatSection ticker={company} />
            </section>
          ) : null}
          {tab === "management" ? (
            <section className="section active" id="section-management">
              <ManagementSection ticker={company} />
            </section>
          ) : null}
          {tab === "valuation" ? (
            <section className="section active" id="section-valuation">
              <ValuationSection ticker={company} />
            </section>
          ) : null}
          {tab === "risks" ? (
            <section className="section active" id="section-risks">
              <RisksSection ticker={company} />
            </section>
          ) : null}
          {tab === "ai" ? (
            <section className="section active" id="section-ai">
              <AiSection ticker={company} />
            </section>
          ) : null}
        </div>
      </main>

      <MetricDrawer
        metricKey={metricKey}
        fact={metricFact}
        onClose={() => setMetricKey(null)}
        onViewSource={(id) => {
          setMetricKey(null);
          openSource(id);
        }}
      />
      <SourceDrawer entityId={sourceEntity} onClose={() => setSourceEntity(null)} />
    </div>
  );
}
