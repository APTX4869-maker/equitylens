"use client";

import { useEffect, useRef, useState } from "react";
import { api, userErrorMessage } from "@/lib/api";
import type { DiscoveryResult, OnboardingTask } from "@/lib/types";

export function AddCompanyDialog({ open, onClose, onCreated }: {
  open: boolean;
  onClose: () => void;
  onCreated: (task: OnboardingTask, ticker: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const requestRef = useRef<AbortController | null>(null);
  const [ticker, setTicker] = useState("");
  const [discovery, setDiscovery] = useState<DiscoveryResult | null>(null);
  const [candidateId, setCandidateId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idempotencyRef = useRef<string | null>(null);

  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement as HTMLElement;
    window.setTimeout(() => inputRef.current?.focus(), 0);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
      if (event.key === "Tab") {
        const dialog = document.querySelector<HTMLElement>("[data-add-company-dialog]");
        const focusable = dialog?.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled)");
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      requestRef.current?.abort();
      window.setTimeout(() => triggerRef.current?.focus(), 0);
    };
  }, [open]);

  if (!open) return null;

  const discover = async () => {
    const normalized = ticker.trim().toUpperCase();
    if (!normalized) { setError("请输入股票代码，例如 KO。"); return; }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true); setError(null); setDiscovery(null); idempotencyRef.current = null;
    try {
      const result = await api.discoverCompany(normalized, controller.signal);
      setTicker(result.ticker);
      setDiscovery(result);
      setCandidateId(result.candidates[0]?.candidate_id ?? "");
      if (!result.candidates.length) setError("未找到可建档证券，请核对代码或交易所。");
    } catch (reason) {
      if (!controller.signal.aborted) setError(`识别失败：${userErrorMessage(reason)} 请核对代码后重试。`);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  const create = async () => {
    if (!discovery || !candidateId || busy) return;
    setBusy(true); setError(null);
    idempotencyRef.current ??= crypto.randomUUID();
    try {
      const task = await api.createOnboarding(discovery, candidateId, idempotencyRef.current);
      onCreated(task, discovery.ticker);
      onClose();
    } catch (reason) {
      setError(`建档未开始：${userErrorMessage(reason)} 请重新识别后再试。`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="onboarding-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="onboarding-dialog" role="dialog" aria-modal="true" aria-labelledby="add-company-title" data-add-company-dialog>
        <header className="onboarding-dialog-head">
          <div><span className="eyebrow">SEC issuer registry</span><h2 id="add-company-title">添加研究公司</h2><p>先确认法律实体与上市证券，再启动可审计建档。</p></div>
          <button className="modal-close" aria-label="关闭添加公司" onClick={onClose}>×</button>
        </header>
        <div className="onboarding-dialog-body">
          <label className="field-label" htmlFor="onboarding-ticker">股票代码</label>
          <div className="ticker-entry">
            <input ref={inputRef} id="onboarding-ticker" value={ticker} maxLength={12} autoComplete="off"
              onChange={(event) => { setTicker(event.target.value.toUpperCase()); setDiscovery(null); setError(null); }}
              onKeyDown={(event) => { if (event.key === "Enter") void discover(); }} placeholder="例如 KO" />
            <button className="primary-action" onClick={() => void discover()} disabled={busy}>{busy && !discovery ? "识别中…" : "识别公司"}</button>
          </div>
          {error ? <div className="action-error" role="alert">{error}</div> : null}
          {discovery ? (
            <div className="candidate-sheet">
              <div className="candidate-status"><span className={`status-dot ${discovery.eligibility.status === "SUPPORTED" ? "pass" : "fail"}`} />{discovery.eligibility.status === "SUPPORTED" ? "符合自动建档范围" : discovery.eligibility.reason ?? "需要人工适配"}</div>
              {discovery.candidates.map((candidate) => (
                <label className={`candidate-row ${candidateId === candidate.candidate_id ? "selected" : ""}`} key={candidate.candidate_id}>
                  <input type="radio" name="candidate" value={candidate.candidate_id} checked={candidateId === candidate.candidate_id} onChange={() => setCandidateId(candidate.candidate_id)} />
                  <span><strong>{candidate.legal_name}</strong><small>{candidate.ticker} · {candidate.exchange} · {candidate.currency} · {candidate.instrument_type}</small></span>
                </label>
              ))}
              <div className="coverage-strip">
                <span>10-K {discovery.coverage.form_counts["10-K"] ?? 0} 份</span><span>10-Q {discovery.coverage.form_counts["10-Q"] ?? 0} 份</span><span>覆盖至 {discovery.coverage.latest_report_date ?? "未知"}</span>
              </div>
              <button className="primary-action full" onClick={() => void create()} disabled={busy || !candidateId || discovery.eligibility.status === "REJECTED"}>{busy ? "正在创建…" : "确认并建档"}</button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
