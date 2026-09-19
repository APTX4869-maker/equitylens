"use client";

import { useMemo, useState } from "react";
import { ApiRequestError, api, userErrorMessage } from "@/lib/api";
import type { OnboardingTask, ProfileCandidate } from "@/lib/types";

const MAX_YAML_BYTES = 512 * 1024;

export function ProfileWorkbench({ task, onChanged }: { task: OnboardingTask; onChanged: (task: OnboardingTask) => void }) {
  const [open, setOpen] = useState(false);
  const [candidate, setCandidate] = useState<ProfileCandidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ path: string; message: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const evidence = useMemo(() => {
    const rows = candidate?.profile.evidence;
    return Array.isArray(rows) ? rows as Record<string, unknown>[] : [];
  }, [candidate]);
  const loadCandidate = async () => {
    setOpen(true);
    if (candidate || loading) return;
    setLoading(true); setError(null);
    try { setCandidate(await api.profileCandidate(task.onboarding_id)); }
    catch (reason) { setError(`候选配置加载失败：${userErrorMessage(reason)}`); }
    finally { setLoading(false); }
  };
  const chooseFile = async (selected?: File) => {
    setFieldErrors([]); setError(null); setFile(selected ?? null); setYamlText("");
    setIdempotencyKey(selected ? crypto.randomUUID() : "");
    if (!selected) return;
    if (selected.size === 0) { setError("YAML 文件为空，请选择包含完整 Profile v2 的文件。"); return; }
    if (selected.size > MAX_YAML_BYTES) { setError("YAML 文件超过 512 KiB 上限。"); return; }
    setYamlText(await selected.text());
  };
  const submit = async () => {
    if (!file || !yamlText || !idempotencyKey) { setError("请先选择有效的审核版 YAML 文件。"); return; }
    setSubmitting(true); setError(null); setFieldErrors([]);
    try { onChanged(await api.importProfileYaml(task.onboarding_id, task.revision, yamlText, idempotencyKey)); }
    catch (reason) {
      if (reason instanceof ApiRequestError) setFieldErrors(reason.detail.field_errors ?? []);
      setError(`导入失败：${userErrorMessage(reason)}`);
    } finally { setSubmitting(false); }
  };
  const refetch = async () => {
    setSubmitting(true); setError(null);
    try { onChanged(await api.refetchOnboarding(task.onboarding_id, task.revision)); }
    catch (reason) { setError(`重新抓取失败：${userErrorMessage(reason)}`); }
    finally { setSubmitting(false); }
  };

  return <section className="profile-workbench" aria-labelledby="profile-workbench-title">
    <div className="workbench-head">
      <div><span className="eyebrow">Reviewed configuration</span><h3 id="profile-workbench-title">发行人适配工作台</h3><p>候选只用于审查；导入审核版后才会恢复构建。</p></div>
      {task.profile_candidate_id ? <button className="secondary-action" onClick={() => void loadCandidate()} aria-expanded={open}>查看候选配置</button> : null}
    </div>
    {open ? <div className="candidate-inspector">
      {loading ? <div className="onboarding-empty">正在读取固定候选…</div> : null}
      {candidate ? <>
        <div className="candidate-metrics"><span><small>未解决字段</small><strong>{candidate.unresolved_fields.length}</strong></span><span><small>固定文档</small><strong>{candidate.snapshot_manifest.length}</strong></span><span><small>状态</small><strong>待审核</strong></span></div>
        <div className="unresolved-list">{candidate.unresolved_fields.map((item) => <article key={item.path}><code>{item.path}</code><strong>{item.reason}</strong><p>{item.action}</p></article>)}</div>
        <div className="evidence-list"><h4>候选证据</h4>{evidence.map((item, index) => <details key={String(item.evidence_id ?? index)}><summary>{String(item.evidence_id ?? `evidence-${index + 1}`)}</summary><dl><dt>来源文档</dt><dd>{String(item.source_document_id ?? "—")}</dd><dt>定位</dt><dd>{String(item.locator ?? "—")}</dd><dt>内容哈希</dt><dd>{String(item.content_sha256 ?? "—")}</dd></dl></details>)}</div>
        <a className="download-link" href={`/api/v1/company-onboardings/${task.onboarding_id}/profile-candidate.yaml`} download>下载候选 YAML</a>
      </> : null}
    </div> : null}
    <div className="yaml-import">
      <label className="file-picker"><span>选择审核版 YAML</span><input aria-label="选择审核版 YAML" type="file" accept=".yaml,.yml,application/yaml,text/yaml" onChange={(event) => void chooseFile(event.target.files?.[0])} /></label>
      <div className="file-readout">{file ? <><strong>{file.name}</strong><span>{file.size.toLocaleString()} bytes</span></> : <span>尚未选择文件 · 最大 512 KiB</span>}</div>
      <button className="primary-action" disabled={!yamlText || submitting} onClick={() => void submit()}>{submitting ? "正在提交…" : "导入并继续"}</button>
    </div>
    {task.profile_id ? <a className="download-link muted" href={`/api/v1/company-onboardings/${task.onboarding_id}/profile-current.yaml`} download>下载当前审核版 YAML</a> : null}
    {task.actions.includes("REFETCH") ? <button className="secondary-action refetch-action" disabled={submitting} onClick={() => void refetch()}>重新抓取固定数据</button> : null}
    {error ? <div className="action-error" role="alert">{error}</div> : null}
    {fieldErrors.length ? <ul className="field-errors">{fieldErrors.map((item) => <li key={`${item.path}-${item.message}`}><code>{item.path}</code>{item.message}</li>)}</ul> : null}
  </section>;
}
