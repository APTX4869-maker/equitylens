"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { OnboardingTask } from "@/lib/types";

const LAST_TASK_KEY = "equitylens:last-onboarding-task";
const isRunning = (task: OnboardingTask) => task.progress
  ? ["QUEUED", "RUNNING"].includes(task.progress.activity)
  : ["QUEUED", "FETCHING", "BUILDING", "VALIDATING", "PUBLISHING"].includes(task.state);

export function OnboardingAttentionButton({ refreshToken, onOpen }: {
  refreshToken: number;
  onOpen: (task?: OnboardingTask) => void;
}) {
  const [tasks, setTasks] = useState<OnboardingTask[]>([]);
  const [count, setCount] = useState(0);
  const running = useRef(false);
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    try {
      const response = await api.onboardings(nextController.signal, true);
      if (nextController.signal.aborted) return;
      setTasks(response.items);
      setCount(response.attention_count ?? response.items.length);
      running.current = response.items.some(isRunning);
    } catch {
      // This global recovery affordance stays quiet; the center has the detailed retry UI.
    }
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void refresh(), 0);
    const poller = window.setInterval(() => { if (running.current) void refresh(); }, 2_000);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearTimeout(kickoff); window.clearInterval(poller);
      controller.current?.abort(); window.removeEventListener("focus", onFocus);
    };
  }, [refresh, refreshToken]);

  if (count === 0) return null;
  const open = () => {
    const lastId = window.localStorage.getItem(LAST_TASK_KEY);
    const selected = tasks.find((task) => task.onboarding_id === lastId) ?? (tasks.length === 1 ? tasks[0] : undefined);
    if (selected) window.localStorage.setItem(LAST_TASK_KEY, selected.onboarding_id);
    onOpen(selected);
  };
  return <button className="onboarding-attention" aria-label={`有 ${count} 个建档任务需要关注`} onClick={open}>
    <span aria-hidden="true">!</span><b>{count}</b><small>建档进度</small>
  </button>;
}
