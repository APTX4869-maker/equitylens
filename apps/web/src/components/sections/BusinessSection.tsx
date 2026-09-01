"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtMoney, signedPct } from "@/lib/format";
import { Card, ErrorBox, Spinner } from "@/components/ui";
import { EChart, seriesOption } from "@/components/charts";
import * as echarts from "echarts";

export type SegmentPoint = {
  period: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  value: number | null;
  status: string;
};

export type SegmentInfo = {
  name: string;
  reported_name: string;
  kind: string;
  series: SegmentPoint[];
  latest: SegmentPoint | null;
  share: number | null;
  growth_yoy: number | null;
  profitability: { status: string; value: number | null; period?: string };
  sources: {
    source_document_id: string;
    form_type: string | null;
    accession_number: string | null;
    filed_at: string | null;
    source_url: string | null;
  }[];
};

export type SegmentsResponse = {
  ticker: string;
  frequency: string;
  kind: string;
  profit_disclosed: boolean;
  total_revenue: number | null;
  segments: SegmentInfo[];
};

export function donutOption(segments: SegmentInfo[]): echarts.EChartsOption {
  const palette = ["#315ca8", "#2c8b72", "#d08a43", "#9a6dc0", "#58a6b5", "#c05555", "#7a8aa5", "#4f7d3f"];
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: unknown) => {
        const item = p as { name: string; value: number; percent: number };
        return `${item.name}<br/>${fmtMoney(item.value)} · ${item.percent.toFixed(1)}%`;
      },
    },
    series: [
      {
        type: "pie",
        radius: ["58%", "88%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: "#fff", borderWidth: 3 },
        label: { show: false },
        emphasis: { label: { show: false } },
        data: segments.map((s, i) => ({
          name: s.name,
          value: s.latest?.value ?? 0,
          itemStyle: { color: palette[i % palette.length] },
        })),
      },
    ],
  };
}

function ProfitBadge({ info }: { info: SegmentInfo }) {
  if (info.profitability.status === "DISCLOSED") {
    return (
      <span className="provenance official">
        官方披露 · 营业利润 {fmtMoney(info.profitability.value)}（{info.profitability.period}）
      </span>
    );
  }
  return (
    <span className="provenance na">
      利润率未单独披露（NOT_DISCLOSED）— 系统不会用公司整体利润率估算
    </span>
  );
}

export function BusinessSection({ ticker }: { ticker: string }) {
  const [kind, setKind] = useState<"segment" | "product">("segment");
  const [annual, setAnnual] = useState<SegmentsResponse | null>(null);
  const [quarterly, setQuarterly] = useState<SegmentsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [a, q] = await Promise.all([
          api.fetchJson<SegmentsResponse>(
            `/api/v1/companies/${ticker}/segments?kind=${kind}&frequency=annual`
          ),
          api.fetchJson<SegmentsResponse>(
            `/api/v1/companies/${ticker}/segments?kind=${kind}&frequency=quarterly`
          ),
        ]);
        if (cancelled) return;
        setAnnual(a);
        setQuarterly(q);
        setSelected((prev) => prev && a.segments.some((s) => s.name === prev) ? prev : (a.segments[0]?.name ?? null));
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, kind, reloadKey]);

  const seg = useMemo(
    () => annual?.segments.find((s) => s.name === selected) ?? annual?.segments[0] ?? null,
    [annual, selected]
  );
  const qseg = useMemo(
    () => quarterly?.segments.find((s) => s.name === (seg?.name ?? "")) ?? null,
    [quarterly, seg]
  );

  const total = annual?.total_revenue ?? null;

  if (error) {
    return (
      <Card>
        <ErrorBox message={error} onRetry={() => setReloadKey((k) => k + 1)} />
      </Card>
    );
  }
  if (!annual) {
    return <Spinner label="正在加载 SEC 分部数据…" />;
  }

  const kindLabel = kind === "segment" ? "公司报告分部" : "产品类别";
  const trendSeries = qseg?.series ?? [];
  const trendLast8 = trendSeries.slice(-8);

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 业务构成</strong> — 分部数据来自 SEC 10-K/10-Q 官方文件（iXBRL 维度解析）。
      </div>
      <div className="section-head">
        <div>
          <h2>业务构成</h2>
          <div className="card-sub">先理解公司靠哪些业务赚钱，再判断增长来自哪里、利润来自哪里。</div>
        </div>
        <div className="seg">
          <button className={kind === "segment" ? "active" : ""} onClick={() => setKind("segment")}>
            公司报告分部
          </button>
          <button className={kind === "product" ? "active" : ""} onClick={() => setKind("product")}>
            产品类别
          </button>
        </div>
      </div>

      <div className="business-layout">
        <Card className="donut-card">
          <div className="card-title">
            {kindLabel} · 年度营收构成
            {total ? `（合计 ${fmtMoney(total)}）` : ""}
          </div>
          <div className="card-sub">点击图形或列表，下钻到业务详情</div>
          <div style={{ marginTop: 8 }}>
            <EChart option={donutOption(annual.segments)} height={260} />
          </div>
          <div className="donut-legend" style={{ marginTop: 6 }}>
            {annual.segments.map((s) => (
              <button
                key={s.name}
                className={`segment-btn ${selected === s.name ? "active" : ""}`}
                onClick={() => setSelected(s.name)}
              >
                <span className="legend-swatch" style={{ background: "#315ca8" }} />
                <span>
                  <strong>{s.name}</strong>
                  <br />
                  <span>
                    {fmtMoney(s.latest?.value ?? null)}
                    {s.growth_yoy != null ? ` · YoY ${signedPct(s.growth_yoy)}` : ""}
                  </span>
                </span>
                <span className="segment-share">{s.share != null ? `${(s.share * 100).toFixed(0)}%` : "—"}</span>
              </button>
            ))}
          </div>
          <div className="beginner-note" style={{ marginTop: 12 }}>
            <div>💡</div>
            <div>
              <strong>披露边界</strong>
              <p>
                系统只展示公司官方披露的分部数据；利润率未披露时明确显示{" "}
                <strong>NOT_DISCLOSED</strong>，不会用公司整体利润率估算。
              </p>
            </div>
          </div>
        </Card>

        <Card className="segment-detail">
          {seg ? (
            <>
              <div className="segment-head">
                <div>
                  <div className="eyebrow">
                    {seg.share != null ? `${(seg.share * 100).toFixed(1)}% of revenue` : "share —"}
                  </div>
                  <h2>{seg.name}</h2>
                  <div className="card-sub">
                    {kindLabel} · {seg.reported_name}（SEC 标签）
                  </div>
                </div>
                <ProfitBadge info={seg} />
              </div>
              <div className="segment-kpis">
                <div className="segment-kpi">
                  <label>{annual.frequency === "annual" ? "FY 收入" : "最新季度收入"}</label>
                  <strong>{fmtMoney(seg.latest?.value ?? null)}</strong>
                </div>
                <div className="segment-kpi">
                  <label>收入占比</label>
                  <strong>{seg.share != null ? `${(seg.share * 100).toFixed(1)}%` : "—"}</strong>
                </div>
                <div className="segment-kpi">
                  <label>同比增速</label>
                  <strong>{seg.growth_yoy != null ? signedPct(seg.growth_yoy) : "—"}</strong>
                </div>
                <div className="segment-kpi">
                  <label>最新期间</label>
                  <strong style={{ fontSize: 13 }}>{seg.latest?.period ?? "—"}</strong>
                </div>
              </div>
              {trendLast8.length >= 2 ? (
                <>
                  <div className="card-title">最近 {trendLast8.length} 期收入趋势（真实）</div>
                  <EChart
                    option={seriesOption(
                      trendLast8.map((p) => p.period),
                      trendLast8.map((p) => p.value),
                      { unit: "currency", color: "#315ca8", name: seg.name }
                    )}
                    height={210}
                  />
                </>
              ) : (
                <div className="card-sub" style={{ marginTop: 10 }}>
                  季度分部数据未披露（仅年度）。
                </div>
              )}
              {trendSeries.some((p) => p.status === "CALCULATED") ? (
                <div className="card-sub" style={{ marginTop: 8 }}>
                  Q4 由「年度 − 9 个月累计」推导（公式 standalone_quarter.ytd_diff.v1），其余为官方披露。
                </div>
              ) : null}
              <div className="source-row" style={{ marginTop: 12 }}>
                {seg.sources.map((src) => (
                  <span className="source-chip-sm" key={src.source_document_id}>
                    ↗ {src.form_type ?? "filing"} · {src.filed_at ?? ""}
                  </span>
                ))}
                <span className="source-chip-sm">来源：SEC EDGAR 官方文件</span>
              </div>
            </>
          ) : (
            <div className="muted">无分部数据</div>
          )}
        </Card>
      </div>
    </>
  );
}
