"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";
import { EChart, barOption } from "@/components/charts";
import { PromiseTracker } from "@/components/sections/PromiseTracker";

type Leader = { name: string; title: string | null; latest_fy: number | null; total_compensation: number | null; source?: string };
type CompRow = { name: string; fiscal_year: number; salary: number | null; stock_awards: number | null; non_equity_incentive: number | null; all_other: number | null; total_compensation: number | null };
type Director = { name: string; occupation: string | null; age: number | null; director_since: string | null; independent: string | null };
type AllocRow = { fiscal_year: number; gross_buybacks: number | null; sbc: number | null; net_buybacks: number | null; dividends: number | null; capex: number | null; operating_cash_flow: number | null; fcf: number | null; diluted_shares: number | null };
type InsiderTx = { insider_name: string; officer_title: string | null; transaction_date: string | null; transaction_code: string | null; security_title: string | null; shares: number | null; price_per_share: number | null; shares_owned_after: number | null; filed_at: string | null; accession_number: string | null; source_url: string | null };
type ScoreDim = { key: string; weight: number; score: number | null; coverage: number; scorable: boolean; criteria: { id: string; score: number | null; evidence: boolean }[]; reason: string | null };

type ManagementResponse = {
  ticker: string;
  leaders: Leader[];
  compensation_table: CompRow[];
  board: (Director & { source?: string })[];
  governance: { board_size: number; independent_count: number };
  capital_allocation: {
    series: AllocRow[];
    latest: AllocRow | null;
    summary: { fcf_cagr?: number | null; capex_cagr?: number | null; buyback_cagr?: number | null; dividend_cagr?: number | null; share_count_5y_change?: number | null };
    mix: { buyback?: number | null; dividend?: number | null; capex?: number | null };
  };
  shareholder_alignment: { gross_buybacks?: number | null; sbc?: number | null; net_buybacks?: number | null; dividends?: number | null; share_count_5y_change?: number | null };
  insider_transactions: InsiderTx[];
  scorecard: { minimum_coverage: number; coverage: number; overall_score: number | null; overall_reason: string | null; dimensions: ScoreDim[] };
  promises: { items: unknown[]; status: string; note: string };
  watch_items: { topic: string; signal: string; next_check: string }[];
};

const DIM_LABELS: Record<string, string> = {
  strategy_execution: "战略与执行",
  capital_allocation: "资本配置",
  shareholder_alignment: "股东利益一致性",
  promise_delivery: "承诺兑现",
  operating_discipline: "经营纪律",
  governance_succession: "公司治理",
};

const TX_CODE: Record<string, string> = {
  S: "卖出", P: "买入", A: "授予", M: "行权", F: "代扣税", G: "赠与", D: "出售至发行人", X: "行权/出售",
};

export function ManagementSection({ ticker }: { ticker: string }) {
  const [data, setData] = useState<ManagementResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openDim, setOpenDim] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<ManagementResponse>(`/api/v1/companies/${ticker}/management`);
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker, reloadKey]);

  if (error) return <Card><ErrorBox message={error} onRetry={() => setReloadKey((k) => k + 1)} /></Card>;
  if (!data) return <Spinner label="正在加载管理层数据…" />;

  const sc = data.scorecard;
  const alloc = data.capital_allocation;
  const series = alloc.series;
  const years = series.map((s) => `FY${s.fiscal_year}`);
  const chartOpt = barOption(
    years,
    [
      { name: "回购", data: series.map((s) => s.gross_buybacks), color: "#315ca8" },
      { name: "分红", data: series.map((s) => s.dividends), color: "#2c8b72" },
      { name: "CapEx", data: series.map((s) => s.capex), color: "#d08a43" },
    ],
    { unit: "currency" }
  );

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 管理层与公司治理</strong> — 高管/薪酬/董事会来自 DEF 14A 代理声明，资本配置来自 SEC 财务事实，
        内部人交易来自 Form 4。评分按确定性 rubric 计算，证据覆盖不足时明确不可用。
      </div>
      <div className="section-head">
        <div>
          <h2>管理层与公司治理</h2>
          <div className="card-sub">核心问题：战略判断是否正确、承诺是否兑现、赚到的钱是否被高质量配置。</div>
        </div>
        <Pill tone={sc.overall_score != null ? "blue" : "warn"}>
          {sc.overall_score != null ? `管理质量 ${sc.overall_score}/100` : "总分证据不足"}
        </Pill>
      </div>

      {/* Scorecard */}
      <Card className="card-pad">
        <div className="card-title">管理层质量评分卡（确定性 rubric）</div>
        <div className="card-sub">
          分数只来自可核验的财务/治理事实；LLM 不参与打分。证据覆盖率需 ≥ {(sc.minimum_coverage * 100).toFixed(0)}% 才给出分数。
        </div>
        {sc.overall_score == null ? (
          <div className="beginner-note" style={{ marginTop: 10 }}>
            <div>!</div>
            <div>
              <strong>当前总分不可用</strong>
              <p>{sc.overall_reason}。已评分维度照常展示；战略/承诺/治理维度需 M7 研究记录补齐证据。</p>
            </div>
          </div>
        ) : null}
        <div className="mgmt-dimensions" style={{ marginTop: 10 }}>
          {sc.dimensions.map((d) => (
            <div className="mgmt-dim" key={d.key}>
              <div
                className="mgmt-dim-head"
                style={{ cursor: "pointer" }}
                onClick={() => setOpenDim(openDim === d.key ? null : d.key)}
              >
                <span>{DIM_LABELS[d.key] ?? d.key}</span>
                <strong>{d.scorable ? d.score : "不可用"}</strong>
              </div>
              <div className="mini-track"><i style={{ width: `${d.coverage * 100}%`, background: d.scorable ? "var(--brand)" : "var(--warn)" }} /></div>
              <p>证据覆盖 {(d.coverage * 100).toFixed(0)}% {d.scorable ? "" : `· ${d.reason ?? ""}`}</p>
              {openDim === d.key ? (
                <div style={{ marginTop: 6 }}>
                  {d.criteria.map((c) => (
                    <div key={c.id} className="criteria-row">
                      <span>{c.id}</span>
                      <em>{c.score != null ? c.score.toFixed(1) : "—"}</em>
                      <small>{c.evidence ? "有公式依据" : "待研究记录"}</small>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </Card>

      {/* Leaders + compensation */}
      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad">
          <div className="card-title">核心高管（DEF 14A）</div>
          <div className="card-sub">薪酬为该财政年度 Summary Compensation Table 总额。</div>
          <div className="leader-grid" style={{ marginTop: 12 }}>
            {data.leaders.map((l) => (
              <div className="leader-card" key={l.name}>
                <div className="leader-role">{l.title ?? "—"}</div>
                <h3>{l.name}</h3>
                <div className="card-sub">
                  FY{l.latest_fy ?? "—"} 总薪酬 {l.total_compensation != null ? fmtMoney(l.total_compensation) : "—"}
                </div>
                <div className="source-row"><span className="source-chip-sm">↗ DEF 14A</span></div>
              </div>
            ))}
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">董事会（DEF 14A）</div>
          <div className="card-sub">
            共 {data.governance.board_size} 人，独立董事 {data.governance.independent_count} 人。
          </div>
          <div style={{ marginTop: 10 }}>
            {data.board.map((b) => (
              <div className="board-row" key={b.name}>
                <div>
                  <strong>{b.name}</strong>
                  <span>{b.director_since ? `董事自 ${b.director_since}` : ""} {b.age ? `· ${b.age} 岁` : ""}</span>
                </div>
                <small>{b.independent?.toLowerCase().startsWith("yes") ? "独立" : b.occupation ? "—" : ""}</small>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Compensation table */}
      <Card className="card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">高管薪酬摘要（SEC 代理声明 · 千美元）</div>
        <div style={{ overflow: "auto", marginTop: 10 }}>
          <table className="promise-table">
            <thead>
              <tr><th>高管</th><th>财年</th><th>工资</th><th>股权奖励</th><th>非股权激励</th><th>其他</th><th>总额</th></tr>
            </thead>
            <tbody>
              {data.compensation_table.map((c, i) => (
                <tr key={i}>
                  <td>{c.name}</td><td>FY{c.fiscal_year}</td>
                  <td>{c.salary != null ? (c.salary / 1000).toFixed(0) : "—"}</td>
                  <td>{c.stock_awards != null ? (c.stock_awards / 1000).toFixed(0) : "—"}</td>
                  <td>{c.non_equity_incentive != null ? (c.non_equity_incentive / 1000).toFixed(0) : "—"}</td>
                  <td>{c.all_other != null ? (c.all_other / 1000).toFixed(0) : "—"}</td>
                  <td><strong>{c.total_compensation != null ? (c.total_compensation / 1000).toFixed(0) : "—"}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Capital allocation */}
      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad">
          <div className="card-title">资本配置去向（真实 · 最近 {series.length} 财年）</div>
          <div className="card-sub">回购 / 分红 / CapEx 的年度金额。</div>
          <EChart option={chartOpt} height={230} />
          <div className="quality-kpis" style={{ marginTop: 8 }}>
            <div className="quality-kpi"><span>5Y FCF CAGR</span><strong>{alloc.summary.fcf_cagr != null ? `${(alloc.summary.fcf_cagr * 100).toFixed(1)}%` : "—"}</strong></div>
            <div className="quality-kpi"><span>5Y CapEx CAGR</span><strong>{alloc.summary.capex_cagr != null ? `${(alloc.summary.capex_cagr * 100).toFixed(1)}%` : "—"}</strong></div>
            <div className="quality-kpi"><span>5Y 股数变化</span><strong>{alloc.summary.share_count_5y_change != null ? `${(alloc.summary.share_count_5y_change * 100).toFixed(1)}%` : "—"}</strong></div>
          </div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">股东利益一致性（真实）</div>
          <div className="card-sub">回购必须扣除股权激励，看真正回到股东手里的净效果。</div>
          <div className="alignment-grid">
            <div className="align-card"><span>名义回购（最新 FY）</span><strong>{fmtMoney(data.shareholder_alignment.gross_buybacks)}</strong><small>来自 10-K 现金流表</small></div>
            <div className="align-card"><span>股权激励 SBC</span><strong>{fmtMoney(data.shareholder_alignment.sbc)}</strong><small>同一财年</small></div>
            <div className="align-card"><span>净回购</span><strong>{fmtMoney(data.shareholder_alignment.net_buybacks)}</strong><small>回购 − SBC</small></div>
            <div className="align-card"><span>5 年稀释股数变化</span><strong>{data.shareholder_alignment.share_count_5y_change != null ? `${(data.shareholder_alignment.share_count_5y_change * 100).toFixed(1)}%` : "—"}</strong><small>正数 = 被稀释</small></div>
          </div>
          <div className="beginner-note" style={{ marginTop: 12 }}>
            <div>→</div>
            <div>
              <strong>资本配置解读</strong>
              <p>
                资本开支增速 {alloc.summary.capex_cagr != null ? `${(alloc.summary.capex_cagr * 100).toFixed(1)}%` : "—"} vs 自由现金流增速{" "}
                {alloc.summary.fcf_cagr != null ? `${(alloc.summary.fcf_cagr * 100).toFixed(1)}%` : "—"}：判断投入是否换来更高现金创造。
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Insider transactions */}
      <Card className="card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">内部人交易（Form 4 · 最近 {data.insider_transactions.length} 笔）</div>
        <div className="card-sub">卖出计划（10b5-1）、代扣税等常见，重点看是否有异常时点的集中买入/卖出。</div>
        <div style={{ overflow: "auto", marginTop: 10 }}>
          <table className="promise-table">
            <thead><tr><th>日期</th><th>内部人</th><th>职务</th><th>类型</th><th>数量</th><th>价格</th><th>交易后持股</th></tr></thead>
            <tbody>
              {data.insider_transactions.map((t, i) => (
                <tr key={i}>
                  <td>{t.transaction_date ?? "—"}</td>
                  <td>{t.insider_name}</td>
                  <td>{t.officer_title ?? "—"}</td>
                  <td>{TX_CODE[t.transaction_code ?? ""] ?? t.transaction_code}</td>
                  <td>{t.shares != null ? Math.round(t.shares).toLocaleString() : "—"}</td>
                  <td>{t.price_per_share != null ? `$${t.price_per_share.toFixed(2)}` : "—"}</td>
                  <td>{t.shares_owned_after != null ? Math.round(t.shares_owned_after).toLocaleString() : "—"}</td>
                </tr>
              ))}
              {data.insider_transactions.length === 0 ? (
                <tr><td colSpan={7} className="muted">暂无 Form 4 数据（已接入管线，等待新申报）</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Promise tracker: live evidence-card verification (M8.6) */}
      <PromiseTracker ticker={ticker} />

      {/* Watch items */}
      <Card className="card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">管理层观察项（可回访验证）</div>
        <div className="watch-grid-v3">
          {data.watch_items.map((w, i) => (
            <div className="watch-v3" key={i}>
              <strong>{i + 1}. {w.topic}</strong>
              <p>{w.signal} · 下次检查：{w.next_check}</p>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
