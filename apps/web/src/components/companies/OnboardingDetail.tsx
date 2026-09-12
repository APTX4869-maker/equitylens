"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { OnboardingTask, ReviewPackage } from "@/lib/types";
import { QualityReportPanel } from "./QualityReportPanel";

const TERMINAL = new Set(["PUBLISHED", "CANCELLED"]);
const STATE_LABELS: Record<string, string> = { QUEUED: "排队中", FETCHING: "抓取 SEC 资料", BUILDING: "构建公司档案", NEEDS_ADAPTATION: "等待适配", VALIDATING: "运行质量检查", NEEDS_REVIEW: "等待维护者复核", PUBLISHING: "正在发布", PUBLISHED: "已发布", FAILED: "执行失败", CANCELLED: "已取消" };

export function OnboardingDetail({ taskId, seed, onChanged }: { taskId: string; seed?: OnboardingTask; onChanged: (task: OnboardingTask) => void }) {
  const [task, setTask] = useState<OnboardingTask | null>(seed ?? null);
  const [review, setReview] = useState<ReviewPackage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);
  const latestState = useRef(seed?.state ?? "QUEUED");

  useEffect(() => {
    let timer: number | undefined;
    let controller = new AbortController();
    let stopped = false;
    const poll = async () => {
      const seq = ++requestSeq.current;
      controller.abort(); controller = new AbortController();
      try {
        const next = await api.onboarding(taskId, controller.signal);
        if (stopped || seq !== requestSeq.current) return;
        latestState.current = next.state;
        setTask(next); setError(null); onChanged(next);
        if (next.state === "NEEDS_REVIEW") {
          const pkg = await api.reviewPackage(taskId, controller.signal);
          if (!stopped && seq === requestSeq.current && pkg.revision === next.revision) setReview(pkg);
        } else setReview(null);
        if (!TERMINAL.has(next.state)) timer = window.setTimeout(poll, document.hidden ? 10_000 : 2_000);
      } catch (reason) {
        if (!stopped && !controller.signal.aborted) { setError(`任务加载失败：${String(reason)} 请稍后重试。`); timer = window.setTimeout(poll, document.hidden ? 10_000 : 2_000); }
      }
    };
    void poll();
    const onVisibility = () => { if (!stopped && !TERMINAL.has(latestState.current)) { window.clearTimeout(timer); timer = window.setTimeout(poll, document.hidden ? 10_000 : 0); } };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { stopped = true; requestSeq.current += 1; controller.abort(); window.clearTimeout(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [taskId, onChanged]);

  if (!task) return <div className="onboarding-empty">正在读取任务…</div>;
  const mutate = async (action: "retry" | "cancel") => {
    try { const next = await api.reviseOnboarding(task.onboarding_id, action, task.revision); latestState.current = next.state; setTask(next); onChanged(next); }
    catch (reason) { setError(`操作失败：${String(reason)} 任务可能已变化，请刷新。`); }
  };
  return <div className="onboarding-detail">
    <div className="task-identity"><div><span className="eyebrow">{task.ticker ?? task.company_id}</span><h2>{task.company_name ?? "公司建档任务"}</h2></div><span className={`task-state state-${task.state.toLowerCase()}`}>{STATE_LABELS[task.state] ?? task.state}</span></div>
    <div className="task-ledger"><div><small>当前步骤</small><strong>{task.current_step ?? "—"}</strong></div><div><small>修订号</small><strong>r{task.revision}</strong></div><div><small>候选数据</small><strong>{task.dataset_id ? "已封存" : "准备中"}</strong></div><div><small>发布版本</small><strong>{task.publication_id ?? "尚未发布"}</strong></div></div>
    {error ? <div className="action-error" role="alert">{error}</div> : null}
    {task.error ? <div className="next-step">{task.error.message ?? "任务执行失败"}。可重试当前步骤，系统会保留已完成产物。</div> : null}
    {review ? <QualityReportPanel task={task} review={review} onChanged={(next) => { setTask(next); onChanged(next); }} /> : null}
    {!review && task.state === "NEEDS_REVIEW" ? <div className="onboarding-empty">正在绑定最新复核包…</div> : null}
    <div className="task-actions">{task.actions.includes("RETRY") ? <button className="primary-action" onClick={() => void mutate("retry")}>重试当前步骤</button> : null}{task.actions.includes("CANCEL") ? <button className="secondary-action" onClick={() => void mutate("cancel")}>取消任务</button> : null}</div>
  </div>;
}
