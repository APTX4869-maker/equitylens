"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, userErrorMessage } from "@/lib/api";
import type { CompanyInfo, CompanyListItem, Fact, MarketQuote, OnboardingTask, OverviewResponse } from "@/lib/types";
import { Sidebar, Topbar, Hero, type TabKey } from "@/components/Shell";
import { OverviewSection } from "@/components/sections/OverviewSection";
import { FinancialsSection } from "@/components/sections/FinancialsSection";
import { BusinessSection } from "@/components/sections/BusinessSection";
import { ManagementSection } from "@/components/sections/ManagementSection";
import { ValuationSection } from "@/components/sections/ValuationSection";
import { RisksSection } from "@/components/sections/RisksSection";
import { AiSection } from "@/components/sections/AiSection";
import { MoatSection } from "@/components/sections/MoatSection";
import { MetricDrawer } from "@/components/MetricDrawer";
import { SourceDrawer } from "@/components/SourceDrawer";
import { AddCompanyDialog } from "@/components/companies/AddCompanyDialog";
import { OnboardingCenter } from "@/components/companies/OnboardingCenter";
import { OnboardingAttentionButton } from "@/components/companies/OnboardingAttentionButton";
import {
  REFRESH_MODULE_LABELS,
  RefreshProgress,
  type RefreshProgressItem,
} from "@/components/RefreshProgress";

type Cached = { info: CompanyInfo; overview: OverviewResponse };
type FreshnessModule = {
  key: string; label: string; as_of: string | null;
  detail: string; status: "ok" | "stale" | "missing"; days_ago: number | null;
};
type Freshness = { modules: FreshnessModule[]; stale_modules: string[]; hint: string | null };
type RefreshModule = {
  status: "ok" | "error" | "skipped";
  retryable: boolean;
  reason?: string | null;
  changed?: boolean;
  finished_at?: string | null;
};
type RefreshResult = {
  refresh_id: string;
  status: "ok" | "partial" | "error";
  modules: Record<string, RefreshModule>;
  review_required: boolean;
};

const FRESHNESS_SHORT_LABELS: Record<string, string> = {
  sec_financials: "财务",
  segments: "分部",
  management: "治理",
  market_quote: "行情",
  valuation_runs: "估值运行",
};

export default function Home() {
  const [companies, setCompanies] = useState<CompanyListItem[]>([]);
  const [company, setCompany] = useState("");
  const [companyListError, setCompanyListError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [centerOpen, setCenterOpen] = useState(false);
  const [createdTask, setCreatedTask] = useState<OnboardingTask | null>(null);
  const [attentionRefresh, setAttentionRefresh] = useState(0);
  const [mode, setMode] = useState<"beginner" | "pro">("beginner");
  const [tab, setTab] = useState<TabKey>("overview");
  const [cache, setCache] = useState<Record<string, Cached>>({});
  const [market, setMarket] = useState<Record<string, MarketQuote | null>>({});
  const [freshness, setFreshness] = useState<Record<string, Freshness | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [metricKey, setMetricKey] = useState<string | null>(null);
  const [metricFact, setMetricFact] = useState<Fact | null>(null);
  const [sourceEntity, setSourceEntity] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [reloadWarning, setReloadWarning] = useState<string | null>(null);
  const [refreshProgress, setRefreshProgress] = useState<Record<string, RefreshProgressItem>>({});
  const [valuationReviewGeneration, setValuationReviewGeneration] = useState<Record<string, number>>({});
  const companyRef = useRef(company);
  const companyListRequestSeq = useRef(0);
  const refreshRequestSeq = useRef(0);
  const dataRequestSeq = useRef(0);

  const loadCompanies = useCallback(async () => {
    const controller = new AbortController();
    const requestSeq = ++companyListRequestSeq.current;
    try {
      const response = await api.companies(controller.signal);
      if (requestSeq !== companyListRequestSeq.current) return;
      const publishedItems = response.items.filter((item) => item.publication_id !== null);
      setCompanies(publishedItems);
      setCompany((current) => {
        const next = current && publishedItems.some((item) => item.ticker === current) ? current : publishedItems[0]?.ticker ?? "";
        companyRef.current = next;
        return next;
      });
      setCompanyListError(null);
    } catch (reason) {
      if (requestSeq === companyListRequestSeq.current && !controller.signal.aborted) {
        setCompanyListError(`研究公司列表加载失败：${String(reason)} 请检查 API 后重试。`);
      }
    }
  }, []);

  const handlePublished = useCallback(() => {
    void loadCompanies();
  }, [loadCompanies]);
  const handleOnboardingChanged = useCallback(() => {
    setAttentionRefresh((value) => value + 1);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCompanies(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCompanies]);

  useEffect(() => {
    document.body.classList.toggle("pro", mode === "pro");
  }, [mode]);

  const selectCompany = useCallback((next: string) => {
    companyRef.current = next;
    refreshRequestSeq.current += 1;
    setRefreshing(false);
    setMetricKey(null);
    setMetricFact(null);
    setSourceEntity(null);
    setRefreshMsg(null);
    setReloadWarning(null);
    setRefreshProgress({});
    setCompany(next);
  }, []);

  // Escape closes any open drawer (metric knowledge / source lineage).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMetricKey(null);
        setSourceEntity(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Fetch per company into a cache; each module settles independently so an
  // optional module (market quote / freshness) failure never hides the core
  // company + overview data (U05).
  useEffect(() => {
    if (!company) return;
    let cancelled = false;
    const controller = new AbortController();
    const requestSeq = ++dataRequestSeq.current;
    const selected = companies.find((item) => item.ticker === company);
    if (!selected) return () => controller.abort();
    const identity = { security_id: selected.security_id, publication_id: selected.publication_id };
    (async () => {
      const [infoR, overviewR, mqR, freshR] = await Promise.allSettled([
        api.company(company, identity, controller.signal),
        api.overview(company, identity, controller.signal),
        api.marketQuote(company, identity, controller.signal),
        api.fetchJson<Freshness>(`/api/v1/companies/${company}/freshness?security_id=${encodeURIComponent(selected.security_id)}&publication_id=${encodeURIComponent(selected.publication_id ?? "")}`, { signal: controller.signal }),
      ]);
      if (cancelled || requestSeq !== dataRequestSeq.current) return;
      if (infoR.status === "fulfilled" && overviewR.status === "fulfilled") {
        setCache((prev) => ({ ...prev, [company]: { info: infoR.value, overview: overviewR.value } }));
        setError(null);
      } else {
        setError("公司或财务总览加载失败");
      }
      if (mqR.status === "fulfilled") {
        setMarket((prev) => ({ ...prev, [company]: mqR.value }));
      }
      if (freshR.status === "fulfilled") {
        setFreshness((prev) => ({ ...prev, [company]: freshR.value }));
      }
      const failedOptionalReads = [
        mqR.status === "rejected" ? "行情" : null,
        freshR.status === "rejected" ? "数据新鲜度" : null,
      ].filter(Boolean);
      setReloadWarning(failedOptionalReads.length
        ? `页面重新读取失败，已保留上次${failedOptionalReads.join("和")}`
        : null);
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [company, companies, reloadKey]);

  const entry = cache[company];
  const openMetric = useCallback((key: string, fact: Fact | null) => {
    setMetricKey(key);
    setMetricFact(fact);
  }, []);

  const openSource = useCallback((entityId: string) => {
    setSourceEntity(entityId);
  }, []);

  const refresh = useCallback(async (modules?: string[]) => {
    const requestCompany = company;
    const requestSeq = ++refreshRequestSeq.current;
    setRefreshing(true);
    setRefreshMsg(null);
    const requested = modules?.length
      ? modules
      : ["financials", "segments", "management", "quotes"];
    setRefreshProgress((previous) => {
      const requestedItems = Object.fromEntries(
        requested.map((moduleName, index) => [
          moduleName,
          {
            ...(modules?.length ? previous[moduleName] : {}),
            phase: index === 0 ? "running" : "pending",
            reason: null,
          } satisfies RefreshProgressItem,
        ])
      );
      return modules?.length ? { ...previous, ...requestedItems } : requestedItems;
    });
    let activeModule: string | null = requested[0] ?? null;
    try {
      const batches = modules?.length
        ? [modules]
        : ["financials", "segments", "management", "quotes"].map((moduleName) => [moduleName]);
      let combined: RefreshResult | null = null;
      for (const [batchIndex, batch] of batches.entries()) {
        const completedModule = batch[0];
        if (!completedModule) continue;
        activeModule = completedModule;
        let response: RefreshResult;
        try {
          response = await api.fetchLongRunningJson<RefreshResult>(
            `/api/v1/companies/${requestCompany}/refresh`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ modules: batch }),
            }
          );
        } catch (reason) {
          response = {
            refresh_id: `client-error-${Date.now()}`,
            status: "partial",
            review_required: false,
            modules: {
              [completedModule]: {
                status: "error",
                retryable: true,
                reason: userErrorMessage(reason),
                changed: false,
                finished_at: new Date().toISOString(),
              },
            },
          };
        }
        if (requestSeq !== refreshRequestSeq.current || companyRef.current !== requestCompany) return;
        const completed = response.modules[completedModule];
        setRefreshProgress((previous) => {
          const next = {
            ...previous,
            [completedModule]: {
              phase: completed?.status === "ok" ? "success" : "error",
              changed: completed?.changed,
              checkedAt: completed?.finished_at,
              reason: completed?.reason ?? (completed ? null : "刷新接口未返回该模块的结果"),
              retryable: completed?.retryable ?? !completed,
            } satisfies RefreshProgressItem,
          };
          const nextModule = batches[batchIndex + 1]?.[0];
          if (nextModule) next[nextModule] = { ...next[nextModule], phase: "running" };
          return next;
        });
        if (completed?.status === "ok") setReloadKey((key) => key + 1);
        if (response.review_required) {
          setValuationReviewGeneration((previous) => ({
            ...previous,
            [requestCompany]: (previous[requestCompany] ?? 0) + 1,
          }));
        }
        if (!combined) {
          combined = response;
          continue;
        }
        const mergedModules: Record<string, RefreshModule> = { ...combined.modules };
        for (const moduleName of batch) {
          if (response.modules[moduleName]) mergedModules[moduleName] = response.modules[moduleName];
        }
        combined = {
          ...response,
          modules: mergedModules,
          review_required: combined.review_required || response.review_required,
        };
      }
      if (!combined) return;
      const d = {
        ...combined,
        status: Object.values(combined.modules).some((moduleResult) => moduleResult.status === "error")
          ? "partial" as const
          : "ok" as const,
      };
      if (requestSeq !== refreshRequestSeq.current || companyRef.current !== requestCompany) return;
      const parts = requested.map((moduleName) => {
        const result = d.modules[moduleName];
        const moduleLabel = REFRESH_MODULE_LABELS[moduleName as keyof typeof REFRESH_MODULE_LABELS] ?? moduleName;
        const statusLabel = result?.status === "ok"
          ? result.changed ? "已更新" : "暂无更新"
          : result?.status === "skipped" ? "未执行" : "失败";
        return `${moduleLabel}${statusLabel}`;
      });
      setRefreshMsg(`刷新完成：${parts.join("、")}`);
    } catch (e) {
      if (requestSeq === refreshRequestSeq.current && companyRef.current === requestCompany) {
        const reason = userErrorMessage(e);
        if (activeModule) {
          const failedModule = activeModule;
          setRefreshProgress((previous) => ({
            ...previous,
            [failedModule]: {
              ...previous[failedModule],
              phase: "error",
              checkedAt: new Date().toISOString(),
              reason,
              retryable: true,
            },
          }));
        }
        setRefreshMsg(`刷新失败：${reason}`);
      }
    } finally {
      if (requestSeq === refreshRequestSeq.current && companyRef.current === requestCompany) {
        setRefreshing(false);
      }
    }
  }, [company]);

  const realDataTabs: TabKey[] = ["overview", "business", "financials", "management", "valuation", "risks", "ai", "moat"];

  return (
    <div className="app">
      <Sidebar companies={companies} company={company} tab={tab} onCompany={selectCompany} onTab={setTab} onAddCompany={() => setAddOpen(true)} onOnboardingCenter={() => setCenterOpen(true)} />
      <main>
        <Topbar companies={companies} mode={mode} onMode={setMode} realData={realDataTabs.includes(tab)} onCompany={selectCompany} onAddCompany={() => setAddOpen(true)} onOnboardingCenter={() => setCenterOpen(true)} />
        <div className="content">
          {companyListError ? <div className="action-error company-list-error" role="alert">{companyListError} <button onClick={() => void loadCompanies()}>重试</button></div> : null}
          {!company && !companyListError ? <div className="onboarding-empty">正在读取已发布公司…</div> : null}
          {company ? <>
          <Hero company={entry?.info ?? null} market={market[company] ?? null} />
          <div className="research-toolbar">
            <div className="tool-left">
              <div className="tool-group">
                <span className="tool-label">数据源</span>
                <span className="tool-value">
                  {entry?.info?.source_freshness?.COMPANYFACTS_SNAPSHOT
                    ? `SEC EDGAR · 抓取于 ${entry.info.source_freshness.COMPANYFACTS_SNAPSHOT.fetched_at.slice(0, 10)}`
                    : "SEC EDGAR"}
                </span>
              </div>
              <div className="tool-group">
                <span className="fresh-dot" />
                <span className="tool-label">最新财报期</span>
                <span className="tool-value">
                  {entry?.overview?.latest_period ? `FY${entry.overview.latest_period.fiscal_year} Q${entry.overview.latest_period.fiscal_quarter}` : "—"}
                </span>
              </div>
              <div
                className="tool-group freshness-group"
                data-testid="freshness-group"
                title={freshness[company]?.hint ?? "各数据模块最近更新时间；过期/缺失模块会标色"}
              >
                <span className="tool-label">数据新鲜度</span>
                {(freshness[company]?.modules ?? []).slice(0, 5).map((m) => {
                  const color = m.status === "ok" ? "#2c8b72" : m.status === "stale" ? "#b58900" : "#c0392b";
                  return (
                    <span
                      key={m.key}
                      className="tool-value"
                      data-testid={`freshness-${m.key}`}
                      title={m.detail}
                      style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 8 }}
                    >
                      <span className="fresh-dot" style={{ background: color }} />
                      {FRESHNESS_SHORT_LABELS[m.key] ?? m.label} {m.as_of?.slice(0, 10) ?? "未同步"}
                    </span>
                  );
                })}
              </div>
              <div className="tool-group">
                <span className="tool-label">视图</span>
                <span className="tool-value">最近 8-12 季</span>
              </div>
            </div>
            <div className="tool-right">
              {refreshMsg ? <span className="tool-value" style={{ marginRight: 8 }}>{refreshMsg}</span> : null}
              {reloadWarning ? <span className="tool-value refresh-reload-warning" role="status">{reloadWarning}</span> : null}
              {Object.entries(refreshProgress)
                .filter(([, item]) => item.phase === "error" && item.retryable)
                .map(([module]) => (
                  <button key={module} className="tool-chip" onClick={() => void refresh([module])} disabled={refreshing}>
                    重试{REFRESH_MODULE_LABELS[module as keyof typeof REFRESH_MODULE_LABELS] ?? module}
                  </button>
                ))}
              <button className="tool-chip" onClick={() => void refresh()} disabled={refreshing}>
                {refreshing ? "刷新中…" : "↻ 刷新数据"}
              </button>
              <button className="tool-chip" onClick={() => setTab("ai")}>✦ 问 AI</button>
            </div>
          </div>

          <RefreshProgress
            items={refreshProgress}
            freshness={freshness[company]?.modules ?? []}
          />

          {tab === "overview" ? (
            <section className="section active" id="section-overview">
              <OverviewSection
                company={entry?.info ?? null}
                overview={entry?.overview ?? null}
                error={error}
                onRetry={() => setReloadKey((k) => k + 1)}
                onGotoTab={setTab}
                onOpenMetric={openMetric}
              />
            </section>
          ) : null}
          {tab === "business" ? (
            <section className="section active" id="section-business">
              <BusinessSection key={`${company}:${reloadKey}`} ticker={company} />
            </section>
          ) : null}
          {tab === "financials" ? (
            <section className="section active" id="section-financials">
              <FinancialsSection key={`${company}:${reloadKey}`} ticker={company} market={market[company] ?? null} onOpenMetric={openMetric} />
            </section>
          ) : null}
          {tab === "moat" ? (
            <section className="section active" id="section-moat">
              <MoatSection key={`${company}:${reloadKey}`} ticker={company} onOpenSource={openSource} />
            </section>
          ) : null}
          {tab === "management" ? (
            <section className="section active" id="section-management">
              <ManagementSection key={`${company}:${reloadKey}`} ticker={company} />
            </section>
          ) : null}
          {tab === "valuation" ? (
            <section className="section active" id="section-valuation">
              <ValuationSection
                key={`${company}:${companies.find((item) => item.ticker === company)?.publication_id ?? "none"}`}
                ticker={company}
                gate={companies.find((item) => item.ticker === company)?.capabilities.find((capability) => capability.module === "valuation") ?? null}
                refreshGeneration={valuationReviewGeneration[company] ?? 0}
                refreshReviewRequired={(valuationReviewGeneration[company] ?? 0) > 0}
              />
            </section>
          ) : null}
          {tab === "risks" ? (
            <section className="section active" id="section-risks">
              <RisksSection key={`${company}:${reloadKey}`} ticker={company} onOpenSource={openSource} />
            </section>
          ) : null}
          {tab === "ai" ? (
            <section className="section active" id="section-ai">
              <AiSection key={`${company}:${reloadKey}`} ticker={company} onOpenSource={openSource} />
            </section>
          ) : null}
          </> : null}
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
      <SourceDrawer
        entityId={sourceEntity}
        publicationId={companies.find((item) => item.ticker === company)?.publication_id}
        onClose={() => setSourceEntity(null)}
      />
      <AddCompanyDialog open={addOpen} onClose={() => setAddOpen(false)} onCreated={(task, ticker) => { setCreatedTask({ ...task, ticker }); setAttentionRefresh((value) => value + 1); setCenterOpen(true); }} />
      <OnboardingAttentionButton refreshToken={attentionRefresh} onOpen={(task) => { if (task) setCreatedTask(task); setCenterOpen(true); }} />
      <OnboardingCenter open={centerOpen} seed={createdTask} onClose={() => setCenterOpen(false)} onPublished={handlePublished} onTaskChanged={handleOnboardingChanged} />
    </div>
  );
}
