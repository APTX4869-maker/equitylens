"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";

type PromiseItem = {
  promise_id: string;
  speaker: string | null;
  statement_date: string;
  promise_text: string;
  normalized_claim: string | null;
  source_label?: string | null;
  source_url?: string | null;
  verification_deadline: string;
  computed_status: "VERIFIED" | "BROKEN" | "OPEN" | "UNVERIFIED";
  status_note: string;
  evidence_ids: string[];
};

const STATUS_META: Record<string, { label: string; tone: "good" | "bad" | "blue" | "neutral" }> = {
  VERIFIED: { label: "已兑现", tone: "good" },
  BROKEN: { label: "未兑现", tone: "bad" },
  OPEN: { label: "跟踪中", tone: "blue" },
  UNVERIFIED: { label: "无法验证", tone: "neutral" },
};

export function PromiseTracker({ ticker }: { ticker: string }) {
  const [data, setData] = useState<{ items: PromiseItem[]; note: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await api.fetchJson<{ items: PromiseItem[]; note: string }>(
          `/api/v1/companies/${ticker}/promises`
        );
        if (!cancelled) { setData(d); setError(null); }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [ticker]);

  if (error) return <Card style={{ marginTop: 16 }}><ErrorBox message={error} /></Card>;
  if (!data) return <Spinner label="正在加载承诺追踪…" />;

  const items = data.items ?? [];
  return (
    <Card className="card-pad" style={{ marginTop: 16 }} data-testid="promise-tracker">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <div>
          <div className="card-title">管理层承诺追踪（Promise Tracker）</div>
          <div className="card-sub">{data.note}</div>
        </div>
        <Pill tone="blue">共 {items.length} 条</Pill>
      </div>
      {items.length === 0 ? (
        <div className="beginner-note" style={{ marginTop: 10 }}>
          <div>·</div>
          <div>
            <strong>暂无承诺证据卡</strong>
            <p>把带来源的证据卡放进 data/evidence/promises/{ticker}/，运行
              {" "}<code>uv run equitylens ingest-promises {ticker}</code>{" "}
              导入；系统会对照 SEC 事实自动判定兑现状态（promise_verify.v1）。</p>
          </div>
        </div>
      ) : (
        <div className="promise-list">
          {items.map((it) => {
            const meta = STATUS_META[it.computed_status] ?? STATUS_META.UNVERIFIED;
            return (
              <div className="risk-item" key={it.promise_id} style={{ marginBottom: 8 }}>
                <Pill tone={meta.tone}>{meta.label}</Pill>
                <div style={{ flex: 1 }}>
                  <h3 style={{ margin: 0 }}>{it.promise_text}</h3>
                  <div className="risk-prob">
                    {it.normalized_claim ?? ""} · {it.speaker ?? "管理层"} · {it.statement_date}
                    {it.verification_deadline ? ` · 验证截止 ${it.verification_deadline}` : ""}
                  </div>
                  <p style={{ margin: "4px 0 0" }}>{it.status_note}</p>
                  <div className="source-row">
                    {it.evidence_ids.slice(0, 4).map((id) => (
                      <span className="source-chip-sm" key={id}>{id.length > 26 ? `${id.slice(0, 26)}…` : id}</span>
                    ))}
                    {it.source_label ? <span className="source-chip-sm">来源：{it.source_label}</span> : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
