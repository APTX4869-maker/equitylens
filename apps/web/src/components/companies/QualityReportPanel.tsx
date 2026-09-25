"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { OnboardingTask, ReviewPackage } from "@/lib/types";

export function QualityReportPanel({ task, review, onChanged }: { task: OnboardingTask; review: ReviewPackage; onChanged: (task: OnboardingTask) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checks = review.quality.checks ?? [];
  const blocked = review.quality.result !== "PASS" || checks.some((check) => check.severity === "BLOCKER" && check.status !== "PASS");

  const decide = async (decision: "APPROVE" | "REJECT") => {
    if (busy || (decision === "APPROVE" && blocked)) return;
    setBusy(true); setError(null);
    try {
      onChanged(await api.reviewOnboarding(task.onboarding_id, {
        expected_revision: task.revision,
        fingerprint: review.fingerprint,
        decision,
        reviewer: "web-maintainer",
        note: decision === "APPROVE" ? "Reviewed in onboarding workspace" : "Returned from onboarding workspace",
      }));
    } catch (reason) {
      setError(`复核未提交：${String(reason)} 请刷新任务后重试。`);
    } finally { setBusy(false); }
  };

  return (
    <section className="quality-panel" aria-label="质量报告">
      <div className="quality-heading"><div><span className="eyebrow">Quality gate</span><h3>发布前质量报告</h3></div><span className={`quality-result ${blocked ? "fail" : "pass"}`}>{blocked ? "BLOCKED" : "PASS"}</span></div>
      <div className="quality-checks">
        {checks.map((check) => <div className="quality-check" key={`${check.check_id}:${check.scope_key}`}><span className={`status-dot ${check.status === "PASS" ? "pass" : "fail"}`} /><div><strong>{check.check_id}</strong><small>{check.scope_key}{check.reason ? ` · ${check.reason}` : ""}</small></div><b>{check.status}</b></div>)}
      </div>
      {blocked ? <div className="next-step">下一步：补齐阻断项后重新验证，生成新的候选指纹再提交复核。</div> : <div className="next-step pass">全部强制检查通过；批准时后端会再次校验任务修订号与候选指纹。</div>}
      {error ? <div className="action-error" role="alert">{error}</div> : null}
      <div className="review-actions"><button className="secondary-action" onClick={() => void decide("REJECT")} disabled={busy}>退回适配</button><button className="primary-action" onClick={() => void decide("APPROVE")} disabled={busy || blocked}>{busy ? "提交中…" : "批准并发布"}</button></div>
    </section>
  );
}
