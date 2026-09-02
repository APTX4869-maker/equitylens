"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";

type RiskItem = {
  category: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  title: string;
  description: string;
  evidence_ids: string[];
  monitoring: string;
  confidence: string;
  generated_by: string;
};

const CATEGORY_LABEL: Record<string, string> = {
  structural: "结构性风险",
  cyclical: "周期性风险",
  execution: "执行风险",
  financial: "财务风险",
  regulatory: "监管风险",
  valuation: "估值风险",
};

export function RisksSection({ ticker }: { ticker: string }) {
  const [data, setData] = useState<{ risks: RiskItem[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<{ risks: RiskItem[] }>(`/api/v1/companies/${ticker}/risks`);
        if (!cancelled) { setData(d); setError(null); }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [ticker, reloadKey]);

  if (error) return <Card><ErrorBox message={error} onRetry={() => setReloadKey((k) => k + 1)} /></Card>;
  if (!data) return <Spinner label="正在生成风险信号…" />;

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 风险清单</strong> — 风险信号由确定性规则从 SEC 财务事实、分部与估值输出生成
        （{data.risks[0]?.generated_by ?? "deterministic-rules.v1"}）；每条都带证据与可回访的观察信号。
      </div>
      <div className="section-head">
        <div>
          <h2>风险清单</h2>
          <div className="card-sub">风险不是列得越多越专业，而是明确“什么事情发生，会让投资逻辑失效”。</div>
        </div>
        <Pill tone="warn">共 {data.risks.length} 项信号</Pill>
      </div>
      <div className="grid grid-2">
        <div className="risk-list">
          {data.risks.map((r) => (
            <div className="risk-item" key={r.title}>
              <div
                className={`risk-level ${r.severity === "HIGH" ? "bad" : r.severity === "MEDIUM" ? "warn" : "good"}`}
                style={{ background: "var(--bad-soft)", color: "var(--bad)" }}
              >
                {r.severity}
              </div>
              <div>
                <h3>{r.title}</h3>
                <p>{r.description}</p>
                <div className="risk-prob">{CATEGORY_LABEL[r.category] ?? r.category} · 置信度 {r.confidence}</div>
                <div className="source-row">
                  <span className="source-chip-sm">↗ 监控：{r.monitoring}</span>
                  <span className="source-chip-sm">依据：{r.generated_by}</span>
                </div>
              </div>
            </div>
          ))}
          {data.risks.length === 0 ? (
            <Card className="card-pad">
              <div className="card-title">当前规则未命中显著风险</div>
              <div className="card-sub">增长、利润率、现金流、资产负债表、集中度与估值敏感性检查均未超阈值。</div>
            </Card>
          ) : null}
        </div>
        <Card className="card-pad">
          <div className="card-title">Thesis Breakers（研究框架）</div>
          <div className="card-sub">真实系统为每家公司维护 3-5 个“逻辑失效条件”，与上方数据信号互补：</div>
          <div className="beginner-note">
            <div>1</div>
            <div>
              <strong>连续两年核心业务增速显著低于行业</strong>
              <p>说明竞争力或市场空间判断可能错了（需要行业数据接入后可自动化）。</p>
            </div>
          </div>
          <div className="beginner-note">
            <div>2</div>
            <div>
              <strong>ROIC 与自由现金流率持续恶化</strong>
              <p>说明增长可能是靠更多资本堆出来的（FCF 转化与 CapEx 强度已在上方信号中监控）。</p>
            </div>
          </div>
          <div className="beginner-note">
            <div>3</div>
            <div>
              <strong>护城河证据被新技术/监管削弱</strong>
              <p>定性变化最终通常会反映到财务指标（如毛利率或客户留存）。</p>
            </div>
          </div>
          <div className="card-sub" style={{ marginTop: 10 }}>
            数据风险自动生成；定性 thesis-breaker 需人工研究维护（后续版本支持笔记）。
          </div>
        </Card>
      </div>
    </>
  );
}
