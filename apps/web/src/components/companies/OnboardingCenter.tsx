"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, userErrorMessage } from "@/lib/api";
import type { OnboardingTask } from "@/lib/types";
import { OnboardingDetail } from "./OnboardingDetail";

const LABELS: Record<string, string> = { NEEDS_REVIEW: "等待维护者复核", PUBLISHED: "已发布", FAILED: "执行失败", CANCELLED: "已取消", QUEUED: "排队中", FETCHING: "抓取中", BUILDING: "构建中", VALIDATING: "验证中", PUBLISHING: "发布中", NEEDS_ADAPTATION: "需要人工适配" };

const LAST_TASK_KEY = "equitylens:last-onboarding-task";

export function OnboardingCenter({ open, seed, onClose, onPublished, onTaskChanged }: { open: boolean; seed?: OnboardingTask | null; onClose: () => void; onPublished: () => void; onTaskChanged?: (task: OnboardingTask) => void }) {
  const [tasks, setTasks] = useState<OnboardingTask[]>(seed ? [seed] : []);
  const [selected, setSelected] = useState<string | null>(seed?.onboarding_id ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);
  const listController = useRef<AbortController | null>(null);
  const changed = useCallback((task: OnboardingTask) => {
    setTasks((items) => items.some((item) => item.onboarding_id === task.onboarding_id) ? items.map((item) => item.onboarding_id === task.onboarding_id ? { ...item, ...task } : item) : [task, ...items]);
    if (task.state === "PUBLISHED") onPublished();
    onTaskChanged?.(task);
  }, [onPublished, onTaskChanged]);

  useEffect(() => {
    if (!seed) return;
    const timer = window.setTimeout(() => { changed(seed); setSelected(seed.onboarding_id); }, 0);
    return () => window.clearTimeout(timer);
  }, [seed, changed]);
  const loadTasks = useCallback(async () => {
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const response = await api.onboardings(controller.signal);
      if (controller.signal.aborted || seq !== requestSeq.current) return;
      setTasks((current) => response.items.map((item) => ({ ...current.find((known) => known.onboarding_id === item.onboarding_id), ...item })));
      setSelected((current) => {
        if (current && response.items.some((item) => item.onboarding_id === current)) return current;
        const stored = window.localStorage.getItem(LAST_TASK_KEY);
        return response.items.find((item) => item.onboarding_id === stored)?.onboarding_id ?? response.items[0]?.onboarding_id ?? null;
      });
      setError(null);
    } catch (reason) {
      if (!controller.signal.aborted && seq === requestSeq.current) setError(`任务列表加载失败：${userErrorMessage(reason)}`);
    } finally {
      if (!controller.signal.aborted && seq === requestSeq.current) setLoading(false);
      if (listController.current === controller) listController.current = null;
    }
  }, []);
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => void loadTasks(), 0);
    return () => { window.clearTimeout(timer); listController.current?.abort(); };
  }, [open, loadTasks]);
  if (!open) return null;
  const active = tasks.find((task) => task.onboarding_id === selected);
  return <div className="onboarding-backdrop"><section className="onboarding-center" role="dialog" aria-modal="true" aria-labelledby="onboarding-center-title">
    <header className="onboarding-dialog-head"><div><span className="eyebrow">Operations ledger</span><h2 id="onboarding-center-title">公司建档中心</h2><p>候选数据通过质量门禁与人工复核后，才进入研究公司列表。</p></div><button className="modal-close" aria-label="关闭建档中心" onClick={onClose}>×</button></header>
    <div className="onboarding-workspace"><aside className="task-list" aria-label="建档任务列表">{tasks.map((task) => <button key={task.onboarding_id} className={selected === task.onboarding_id ? "active" : ""} onClick={() => { setSelected(task.onboarding_id); window.localStorage.setItem(LAST_TASK_KEY, task.onboarding_id); }}><span><strong>{task.ticker ?? task.company_id}</strong><small>{task.company_name ?? task.onboarding_id.slice(0, 12)}</small></span><b>{LABELS[task.state] ?? task.state}</b></button>)}{!tasks.length && !error && !loading ? <div className="onboarding-empty">暂无建档任务</div> : null}{error ? <div className="action-error" role="alert">{error}<button className="secondary-action" onClick={() => void loadTasks()} disabled={loading}>{loading ? "正在重试…" : "重试任务列表"}</button></div> : null}</aside><main className="task-stage">{active ? <OnboardingDetail key={active.onboarding_id} taskId={active.onboarding_id} seed={active} onChanged={changed} /> : <div className="onboarding-empty">选择一项任务查看进度</div>}</main></div>
  </section></div>;
}
