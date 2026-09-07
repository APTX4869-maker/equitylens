"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProvenanceNode } from "@/lib/types";
import { statusLabel } from "@/lib/format";
import { ErrorBox } from "@/components/ui";

function NodeRow({ node, depth }: { node: ProvenanceNode; depth: number }) {
  const f = node.fields;
  const title =
    node.kind === "canonical_fact"
      ? `${String(f.metric)} · ${String(f.period_type ?? "")}${f.fiscal_quarter ? ` FY${String(f.fiscal_year)}Q${String(f.fiscal_quarter)}` : f.fiscal_year ? ` FY${String(f.fiscal_year)}` : ""}`
      : node.kind === "raw_fact"
        ? `${node.label ?? ""}`
        : node.label ?? "";
  return (
    <div className="prov-node" style={{ marginLeft: depth * 18 }}>
      <div className="prov-head">
        <span className={`prov-kind kind-${node.kind}`}>{node.kind === "canonical_fact" ? "规范化事实" : node.kind === "raw_fact" ? "原始事实" : "来源文档"}</span>
        <strong>{title}</strong>
        {node.kind === "canonical_fact" ? <em>{statusLabel(f.status as string)}</em> : null}
      </div>
      <div className="prov-fields">
        {node.kind === "canonical_fact" ? (
          <>
            <span>值：{f.value !== null && f.value !== undefined ? Number(f.value).toLocaleString("en-US") : "—"} {String(f.unit ?? "")}</span>
            {f.period_end ? <span>期末：{String(f.period_end)}</span> : null}
            {f.mapping_rule_id ? <span>规则：{String(f.mapping_rule_id)}</span> : null}
            {f.mapping_version ? <span>版本：{String(f.mapping_version)}</span> : null}
          </>
        ) : node.kind === "raw_fact" ? (
          <>
            <span>概念：{String(f.taxonomy)}:{String(f.concept)}</span>
            {f.raw_value !== null && f.raw_value !== undefined ? <span>原始值：{String(f.raw_value)} {String(f.unit ?? "")}</span> : null}
            {f.form_type ? <span>表单：{String(f.form_type)}</span> : null}
            {f.accession_number ? <span>Accession：{String(f.accession_number)}</span> : null}
            {f.filed_at ? <span>提交日：{String(f.filed_at).slice(0, 10)}</span> : null}
          </>
        ) : (
          <>
            {f.provider ? <span>来源：{String(f.provider)}</span> : null}
            {f.document_type ? <span>文档：{String(f.document_type)}</span> : null}
            {f.fetched_at ? <span>抓取于：{String(f.fetched_at)}</span> : null}
            {f.content_sha256 ? <span className="mono">SHA-256：{String(f.content_sha256).slice(0, 20)}…</span> : null}
            {f.source_url ? (
              <a href={String(f.source_url)} target="_blank" rel="noreferrer" className="prov-link">
                ↗ 打开官方来源
              </a>
            ) : null}
          </>
        )}
      </div>
      {node.parents.map((p) => (
        <NodeRow key={p.entity_id} node={p} depth={depth + 1} />
      ))}
    </div>
  );
}

export function SourceDrawer({
  entityId,
  onClose,
}: {
  entityId: string | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<{ tree: ProvenanceNode; entity: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!entityId) return;
    api
      .provenance(entityId)
      .then((d) => {
        setData({ tree: d.tree, entity: entityId });
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [entityId]);

  const loading = !data || data.entity !== entityId;

  if (!entityId) return null;
  return (
    <div className="modal-backdrop open" onClick={onClose}>
      <div className="modal wide" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>数据来源与溯源</h2>
            <p className="card-sub">结论 → 证据 → 来源。每一个数字都可以追溯到 SEC 原始文件。</p>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {error ? <ErrorBox message={error} /> : null}
          {loading && !error ? <div className="muted">加载溯源链…</div> : null}
          {data && !loading ? <NodeRow node={data.tree} depth={0} /> : null}
          <div className="beginner-note" style={{ marginTop: 16 }}>
            <div>!</div>
            <div>
              <strong>为什么必须看来源？</strong>
              <p>防止“看着财报猜数字”：每个数字都有官方文件、概念标签、期间和抓取时间戳。若来源缺失，该数字不应被信任。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
