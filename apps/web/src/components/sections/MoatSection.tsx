"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";

type MoatSignal = {
  dimension: string;
  verdict: "strength" | "watch" | "concern";
  title: string;
  detail: string;
  evidence_ids: string[];
  value_label: string | null;
};

type MoatResponse = {
  ticker: string;
  method: string;
  signals: MoatSignal[];
  qualitative_gaps: { dimension: string; note: string }[];
  summary: string;
  demo: boolean;
};

const VERDICT_META: Record<string, { label: string; cls: string }> = {
  strength: { label: "强信号", cls: "good" },
  watch: { label: "观察", cls: "warn" },
  concern: { label: "警示", cls: "bad" },
};

export function MoatSection({ ticker, onOpenSource }: { ticker: string; onOpenSource: (id: string) => void }) {
  const [data, setData] = useState<MoatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<MoatResponse>(`/api/v1/companies/${ticker}/moat`);
        if (!cancelled) { setData(d); setError(null); }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [ticker, reloadKey]);

  if (error) return <Card><ErrorBox message={error} onRetry={() => setReloadKey((k) => k + 1)} /></Card>;
  if (!data) return <Spinner label="正在从 SEC 数字证据生成护城河信号…" />;

  const nStr = data.signals.filter((s) => s.verdict === "strength").length;

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 护城河证据</strong> — 每条信号都来自 SEC 财务事实/分部的确定性计算（{data.method}）；
        无 SEC 数字证据的定性维度（品牌、网络效应等）以“证据缺口”显式列出，不参与评估、不打分。
      </div>
      <div className="section-head">
        <div>
          <h2>护城河分析</h2>
          <div className="card-sub">护城河不是一个分数，而是“哪些证据支持、哪些证据缺失”。先看数字能证明什么。</div>
        </div>
        <Pill tone={nStr >= 4 ? "good" : "warn"}>
          {nStr} 项强信号 · {data.signals.length - nStr} 项观察/警示 · {data.qualitative_gaps.length} 项证据缺口
        </Pill>
      </div>

      <Card className="card-pad" style={{ marginBottom: 14 }}>
        <div className="card-title">结论（仅基于可用证据）</div>
        <p style={{ fontSize: 13, lineHeight: 1.7, color: "var(--muted)", margin: "6px 0 0" }}>{data.summary}</p>
      </Card>

      <div className="grid grid-2">
        <div className="risk-list">
          {data.signals.map((s) => {
            const meta = VERDICT_META[s.verdict];
            return (
              <div className="risk-item" key={s.title + s.dimension}>
                <div className={`risk-level ${meta.cls}`}>{meta.label}</div>
                <div>
                  <h3>{s.title}</h3>
                  <div className="risk-prob">{s.dimension} · {s.value_label ?? ""}</div>
                  <p>{s.detail}</p>
                  <div className="source-row">
                    {s.evidence_ids.slice(0, 6).map((id) => (
                      <button
                        key={id}
                        className="source-chip-sm"
                        style={{ border: "none", cursor: "pointer", fontFamily: "inherit" }}
                        title="打开来源抽屉（canonical fact 可溯源）"
                        onClick={() => { if (id.startsWith("cf_") || id.startsWith("valuation_model")) onOpenSource(id); }}
                      >
                        {id.startsWith("cf_") ? "↗ " : ""}{id.startsWith("segment:") ? `分部证据：${id.slice(8)}` : id.length > 26 ? `${id.slice(0, 26)}…` : id}
                      </button>
                    ))}
                    <span className="source-chip-sm">依据：{data.method}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <Card className="card-pad">
          <div className="card-title">证据缺口（不评分）</div>
          <div className="card-sub">
            这些维度是真实护城河的重要部分，但 SEC 财报没有相应数字——缺证据≠没有护城河，只代表当前不可判定。
          </div>
          <div style={{ marginTop: 8 }}>
            {data.qualitative_gaps.map((g) => (
              <div key={g.dimension} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <strong style={{ color: "var(--navy)", fontSize: 13 }}>{g.dimension}</strong>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{g.note}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
