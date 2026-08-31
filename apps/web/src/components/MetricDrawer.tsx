"use client";

import { metricKnowledge } from "@/lib/metricKnowledge";
import type { Fact } from "@/lib/types";
import { statusLabel } from "@/lib/format";

export function MetricDrawer({
  metricKey,
  onClose,
  onViewSource,
  fact,
}: {
  metricKey: string | null;
  onClose: () => void;
  onViewSource: (entityId: string) => void;
  fact?: Fact | null;
}) {
  if (!metricKey) return null;
  const k = metricKnowledge[metricKey] ?? metricKnowledge.revenue;
  return (
    <div className="modal-backdrop open" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>{k.en}</h2>
            <p>{k.cn}</p>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div className="explain-grid">
            <div className="explain-box">
              <h4>它回答什么问题？</h4>
              <p>{k.question}</p>
            </div>
            <div className="explain-box">
              <h4>定义</h4>
              <p>{k.definition}</p>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <div className="card-sub" style={{ marginBottom: 5 }}>常见公式</div>
            <div className="formula">{k.formula}</div>
          </div>
          <div className="plain-box">
            <strong>用人话理解：</strong>
            <br />
            {k.plain}
          </div>
          <div className="warning-box">
            <strong>⚠ 注意：</strong> {k.warning}
          </div>
          {fact ? (
            <div className="source-row" style={{ marginTop: 14 }}>
              <span className={`provenance ${fact.status === "CALCULATED" ? "calc" : "official"}`}>
                {statusLabel(fact.status)}
              </span>
              <span className="card-sub">当前公司值：{Number(fact.value).toLocaleString("en-US")} {fact.unit}</span>
              <button className="text-link" onClick={() => onViewSource(fact.canonical_fact_id)}>
                查看来源 →
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
