import type { OnboardingProgress as Progress } from "@/lib/types";

const ACTIVITY_LABEL: Record<string, string> = {
  QUEUED: "排队中", RUNNING: "进行中", WAITING_FOR_MAINTAINER: "等待维护者",
  FAILED: "失败", CANCELLED: "已取消", COMPLETED: "已完成",
};

export function OnboardingProgress({ progress }: { progress?: Progress }) {
  if (!progress) return null;
  return <section className="progress-ledger" aria-label="建档阶段">
    <div className="progress-summary">
      <div><span className="eyebrow">Pipeline position</span><strong>{progress.completed} / {progress.total} 阶段完成</strong></div>
      <b>{progress.percent}%</b>
    </div>
    <div className="progress-track" role="progressbar" aria-label="建档总进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}>
      {progress.stages.map((stage) => {
        const spoken = stage.status === "COMPLETED" ? "已完成" : stage.status === "CURRENT" ? "进行中" : "尚未开始";
        return <div key={stage.id} className={`progress-segment progress-${stage.status.toLowerCase()}`} aria-label={`${stage.label}：${spoken}`}>
          <span className="progress-segment-bar" aria-hidden="true" />
          <span className="progress-index">{stage.status === "COMPLETED" ? "✓" : progress.stages.indexOf(stage) + 1}</span>
          <span><strong>{stage.label}</strong><small>{stage.status === "CURRENT" ? ACTIVITY_LABEL[progress.activity] : spoken}</small></span>
        </div>;
      })}
    </div>
    {progress.stalled ? <div className="progress-stalled" role="alert">运行心跳已超过 45 秒未更新，请检查后台任务。</div> : null}
  </section>;
}
