"use client";

import type { CompanyListItem } from "@/lib/types";
import type { TabKey } from "@/components/Shell";

const MODULES = [
  { key: "financials", label: "财务研究" },
  { key: "segments", label: "业务分部" },
  { key: "market", label: "行情" },
  { key: "valuation", label: "估值" },
] as const;

function explanation(module: string, status: string) {
  switch (status) {
    case "READY":
      if (module === "market") return { label: "行情接口已接入", tone: "neutral", text: "不代表行情已同步或未过期。观察时点与抓取时间请看行情提示；过期价格不参与现价对比。" };
      if (module === "valuation") return { label: "基准已确认", tone: "ready", text: "可按当前发布与冻结基准探索估值；模型适用性、估计输入和行情状态仍需分别判断。" };
      return { label: "可研究", tone: "ready", text: "已有发布数据；期间和证据缺口以各页面标注为准，不代表全部披露均已覆盖。" };
    case "NEEDS_CONFIGURATION":
      return { label: "待配置或确认", tone: "attention", text: "先进入审核查看能否生成基准。草案可用时由你核对并确认；缺公司配置或关键事实时需维护者处理，不是仍在后台加工。" };
    case "DATA_BLOCKED":
    case "BLOCKED":
      return { label: "数据阻断", tone: "blocked", text: "关键事实或质量门禁未通过。需维护者核对证据与映射，不能用重载或确认假设绕过。其他已有模块仍可研究。" };
    case "NOT_DISCLOSED":
      return { label: "发布未覆盖", tone: "attention", text: module === "segments" ? "当前发布无分部事实，不等于公司没有披露。请在业务构成核对证据缺口；需维护者适配或确认不适用。" : "当前发布未覆盖该模块事实；需核对原始披露和适配情况，不补猜测数据。" };
    case "UNSUPPORTED_MODEL":
      return { label: "模型不适用或未验证", tone: "attention", text: "当前报告模板没有经过验证的估值模型，不能靠确认假设解除。需维护者验证适用模型；先研究已开放模块，不输出伪造估值。" };
    case "UNKNOWN":
      return { label: "未记录", tone: "neutral", text: "当前发布未记录此模块能力，不能据此认定可用；需维护者核对能力记录。" };
    default:
      return { label: "状态待核实", tone: "neutral", text: "收到尚未识别的能力状态，不按可用处理；需维护者核对，原始原因保留在下方。" };
  }
}

export function CompanyCapabilities({ company, onNavigate }: {
  company: CompanyListItem;
  onNavigate: (tab: TabKey) => void;
}) {
  const modules = [...MODULES, ...company.capabilities.filter(cap => !MODULES.some(module => module.key === cap.module)).map(cap => ({ key: cap.module, label: cap.module }))];
  const restricted = modules.filter(module => company.capabilities.find(cap => cap.module === module.key)?.status !== "READY").length;
  return <details className="company-capabilities" data-testid="company-capabilities">
    <summary><strong>{company.ticker} · 模块能力与下一步</strong><span>{restricted ? `${restricted} 项需处理` : "按模块查看覆盖与限制"}</span></summary>
    <p className="capability-boundary">已发布不等于所有模块可用。以下状态属于当前发布版本；支持范围、披露覆盖、行情新鲜度和估值确认分别判断。</p>
    <div className="capability-grid">
      {modules.map(module => {
        const cap = company.capabilities.find(item => item.module === module.key);
        const state = cap?.status ?? "UNKNOWN";
        const description = explanation(module.key, state);
        return <section key={module.key} className={`capability-card capability-${description.tone}`} data-testid={`capability-${module.key}`}>
          <header><h3>{module.label}</h3><span>{description.label}</span></header>
          <p>{description.text}</p>
          <details className="capability-reason"><summary>原始状态与原因</summary><p>{state} · {cap?.reason ?? "未提供原因"}</p></details>
          {module.key === "financials" && state === "READY" ? <button className="text-link" onClick={() => onNavigate("financials")}>查看财务数据</button> : null}
          {module.key === "segments" && ["READY", "NOT_DISCLOSED"].includes(state) ? <button className="text-link" onClick={() => onNavigate("business")}>查看分部证据与缺口</button> : null}
          {module.key === "valuation" && state === "NEEDS_CONFIGURATION" ? <button className="text-link" onClick={() => onNavigate("valuation")}>查看估值审核与阻塞</button> : null}
          {module.key === "valuation" && state === "READY" ? <button className="text-link" onClick={() => onNavigate("valuation")}>进入估值工作区</button> : null}
        </section>;
      })}
    </div>
  </details>;
}
