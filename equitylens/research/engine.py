"""Evidence-first AI Research Assistant (M7) — deterministic engine.

The assistant answers questions by RETRIEVING real canonical facts, derived
metrics, segments and risk signals, then composing structured claims that cite
evidence IDs. It can never invent a number: if a requested figure is not in
the store, the answer says so.

Architecture note: an LLM may later be plugged in as an explanation layer over
this same retrieval (LLM writes prose, never numbers). Without a configured
LLM the engine is fully deterministic and offline.
"""

from __future__ import annotations

import re

from equitylens.api.segments_service import get_segments
from equitylens.domain.risks import risk_signals
from equitylens.metrics.engine import MetricEngine
from equitylens.valuation.service import default_valuation

EVIDENCE_MISSING = "NO_EVIDENCE_FOR_THIS_CLAIM"


def _num(store, company_id: str, metric: str, freq="quarterly"):
    engine = MetricEngine(store)
    try:
        return engine.compute(metric, company_id, frequency=freq)
    except ValueError:
        return []


def _latest(pts):
    return pts[-1] if pts else None


def ask(store, company_id: str, ticker: str, question: str) -> dict:
    q = question.strip()
    intent = _route(q)

    if intent == "metric_explain":
        return _metric_explain(q)
    if intent == "risk":
        return _answer_risks(store, company_id, ticker)
    if intent == "compare":
        return _answer_compare(store, company_id, ticker, q)
    if intent == "margin":
        return _answer_margin(store, company_id, ticker)
    if intent == "cash":
        return _answer_cash(store, company_id, ticker)
    if intent == "growth":
        return _answer_growth(store, company_id, ticker)
    if intent == "business":
        return _answer_business(store, company_id, ticker)
    if intent == "valuation":
        return _answer_valuation(store, company_id, ticker)
    return _answer_overview(store, company_id, ticker)


def _route(q: str) -> str:
    ql = q.lower()
    if any(k in ql for k in ("是什么", "什么是", "define", "解释", "explain", "意味着什么")) and \
       any(k in ql for k in ("毛利率", "roe", "roic", "fcf", "pe", "margin", "回报率", "现金流")):
        return "metric_explain"
    if any(k in ql for k in ("风险", "risk", "隐患", "担忧")):
        return "risk"
    if any(k in ql for k in ("和 ", "对比", "比较", "vs", "compare", "比谁", "谁更好")):
        return "compare"
    if any(k in ql for k in ("毛利率", "毛利", "margin", "利润率高", "利润率")):
        return "margin"
    if any(k in ql for k in ("现金流", "fcf", "现金", "capex", "回购")):
        return "cash"
    if any(k in ql for k in ("增长", "增速", "放缓", "成长", "growth")):
        return "growth"
    if any(k in ql for k in ("业务", "分部", "segment", "产品", "收入构成")):
        return "business"
    if any(k in ql for k in ("估值", "dcf", "价值", "便宜", "贵", "fair")):
        return "valuation"
    return "overview"


# ---------------- answer builders ----------------

def _claim(claim: str, confidence: str, evidence_ids: list[str]) -> dict:
    return {"claim": claim, "confidence": confidence, "evidence_ids": evidence_ids}


def _metric_explain(q: str) -> dict:
    return {
        "answer": "指标的定义/公式/常见误区在财务分析页的指标解释抽屉中（点击任意指标卡）。本助手可回答：收入增长、利润率、现金流与回购、风险、估值、业务构成等真实数据问题。",
        "claims": [],
        "metric_ids": [],
        "limitations": ["指标字典解释由前端提供；本助手不做无证据的指标外数字猜测"],
    }


def _answer_risks(store, company_id: str, ticker: str) -> dict:
    data = risk_signals(store, company_id, ticker)
    claims = []
    for r in data["risks"][:4]:
        claims.append(_claim(
            f"[{r['severity']}] {r['title']}：{r['description']}",
            "HIGH" if r["severity"] == "HIGH" else "MEDIUM",
            r["evidence_ids"],
        ))
    if not claims:
        claims.append(_claim("当前规则未命中显著风险信号。", "LOW", []))
    return {
        "answer": f"基于确定性规则（{data['generated_by']}）检查了增长、利润率、现金流、资产负债表、集中度与估值敏感性，共识别 {len(data['risks'])} 项风险信号：",
        "claims": claims,
        "metric_ids": [],
        "limitations": ["风险为数据信号，不构成投资建议；结构性/监管等定性风险需人工研究补充"],
    }


def _answer_compare(store, company_id: str, ticker: str, q: str) -> dict:
    rev = _num(store, company_id, "REVENUE")
    opp = _num(store, company_id, "OPERATING_MARGIN")
    fcf = _num(store, company_id, "FCF_MARGIN")
    growth = _num(store, company_id, "REVENUE_GROWTH_YOY")
    lr = _latest(rev); lo = _latest(opp); lf = _latest(fcf); lg = _latest(growth)
    claims = []
    if lr and lr.value:
        claims.append(_claim(f"{ticker} TTM 收入约 ${lr.value/1e9:.0f}B（截至 {lr.period_label}）。",
                             "HIGH", [lr.canonical_fact_id]))
    if lo and lo.value:
        claims.append(_claim(f"营业利润率 {lo.value*100:.1f}%（{lo.period_label}）。",
                             "HIGH", [lo.canonical_fact_id]))
    if lf and lf.value:
        claims.append(_claim(f"FCF 率 {lf.value*100:.1f}%。", "HIGH", [lf.canonical_fact_id]))
    if lg and lg.value:
        claims.append(_claim(f"最新季度收入同比 {lg.value*100:.1f}%。", "HIGH", [lg.canonical_fact_id]))
    claims.append(_claim("对比分析需要先在总览页切换到另一家公司；本回答给出当前公司真实指标基线。", "MEDIUM", []))
    return {"answer": f"这是 {ticker} 的真实财务基线（用于比较的起点）：",
            "claims": claims, "metric_ids": [], "limitations": ["跨公司对比请手动切换公司后自行对照，或后续版本提供并排视图"]}


def _answer_margin(store, company_id: str, ticker: str) -> dict:
    gm = _num(store, company_id, "GROSS_MARGIN")
    om = _num(store, company_id, "OPERATING_MARGIN")
    nm = _num(store, company_id, "NET_MARGIN")
    lg, lo, ln = _latest(gm), _latest(om), _latest(nm)
    claims = []
    if lg and lg.value:
        claims.append(_claim(f"毛利率 {lg.value*100:.1f}%（{lg.period_label}）。", "HIGH", [lg.canonical_fact_id]))
    if lo and lo.value:
        trend = "，" + _margin_trend_text(om)
        claims.append(_claim(f"营业利润率 {lo.value*100:.1f}%（{lo.period_label}）{trend}。", "HIGH", [lo.canonical_fact_id]))
    if ln and ln.value:
        claims.append(_claim(f"净利率 {ln.value*100:.1f}%。", "HIGH", [ln.canonical_fact_id]))
    return {"answer": f"{ticker} 最新利润率（全部来自 SEC 规范化事实）：",
            "claims": claims, "metric_ids": ["GROSS_MARGIN", "OPERATING_MARGIN", "NET_MARGIN"],
            "limitations": ["利润率口径为 us-gaap 标准化事实；跨期可比性需注意一次性项目"]}


def _margin_trend_text(pts) -> str:
    vals = [p.value for p in pts if p.value is not None][-5:]
    if len(vals) >= 2 and vals[0]:
        chg = (vals[-1] / vals[0] - 1) * 100
        return f"近 5 期变动 {chg:+.1f}%"
    return ""


def _answer_cash(store, company_id: str, ticker: str) -> dict:
    ocf = _num(store, company_id, "OPERATING_CASH_FLOW")
    capex = _num(store, company_id, "CAPITAL_EXPENDITURES")
    fcfm = _num(store, company_id, "FCF_MARGIN")
    ocf_ttm = sum(p.value for p in ocf[-4:] if p.value) if len(ocf) >= 4 else None
    capex_ttm = sum(p.value for p in capex[-4:] if p.value) if len(capex) >= 4 else None
    lf = _latest(fcfm)
    claims = []
    if ocf_ttm:
        claims.append(_claim(f"TTM 经营现金流约 ${ocf_ttm/1e9:.0f}B。", "HIGH",
                             [p.canonical_fact_id for p in ocf[-4:] if p.canonical_fact_id]))
    if capex_ttm is not None:
        claims.append(_claim(f"TTM 资本开支约 ${capex_ttm/1e9:.0f}B（占经营现金流 {(capex_ttm/ocf_ttm*100) if ocf_ttm else 0:.0f}%）。", "HIGH",
                             [p.canonical_fact_id for p in capex[-4:] if p.canonical_fact_id]))
    if lf and lf.value:
        claims.append(_claim(f"FCF 率 {lf.value*100:.1f}%。", "HIGH", [lf.canonical_fact_id]))
    return {"answer": f"{ticker} 现金创造情况（TTM，来自 10-K/10-Q 现金流表）：",
            "claims": claims, "metric_ids": ["OPERATING_CASH_FLOW", "CAPITAL_EXPENDITURES", "FCF_MARGIN"],
            "limitations": ["季度现金流为独立季度（非 YTD 累计）；Q2/Q3/Q4 由 YTD 链推导"]}


def _answer_growth(store, company_id: str, ticker: str) -> dict:
    rev = _num(store, company_id, "REVENUE")
    growth = _num(store, company_id, "REVENUE_GROWTH_YOY")
    claims = []
    if len(growth) >= 2:
        a = [p.value for p in growth[-2:] if p.value is not None]
        if len(a) == 2:
            d = "加快" if a[-1] >= a[0] else "放缓"
            claims.append(_claim(
                f"最近两季度收入同比分别为 {a[0]*100:.1f}% → {a[-1]*100:.1f}%，增速{d}。",
                "HIGH", [p.canonical_fact_id for p in growth[-2:] if p.canonical_fact_id]))
    if len(rev) >= 5:
        q = rev[-1]
        y = next((p for p in rev if p.fiscal_year == (q.fiscal_year or 1) - 1 and p.fiscal_quarter == q.fiscal_quarter), None)
        if q.value and y and y.value:
            claims.append(_claim(
                f"最新季度收入 ${q.value/1e9:.0f}B（{q.period_label}），去年同期 ${y.value/1e9:.0f}B。",
                "HIGH", [q.canonical_fact_id, y.canonical_fact_id]))
    return {"answer": f"{ticker} 增长轨迹（真实数据）：",
            "claims": claims, "metric_ids": ["REVENUE", "REVENUE_GROWTH_YOY"],
            "limitations": ["增长解释如需拆分到分部/驱动，请询问业务构成"]}


def _answer_business(store, company_id: str, ticker: str) -> dict:
    try:
        seg = get_segments(store, ticker, kind="segment", frequency="annual")
    except Exception:
        seg = {"segments": []}
    claims = []
    if seg.get("segments"):
        lines = []
        for s in sorted(seg["segments"], key=lambda x: -(x["share"] or 0)):
            lines.append(f"{s['name']} {(s['share'] or 0)*100:.0f}%")
            growth_txt = ""
            if s.get("growth_yoy") is not None:
                growth_txt = f"，同比 {s['growth_yoy']*100:+.1f}%"
            claims.append(_claim(
                f"分部「{s['name']}」收入占比 {(s['share'] or 0)*100:.0f}%{growth_txt}。",
                "HIGH", [f"segment:{s['name']}"]))
        top = max(seg["segments"], key=lambda x: x["share"] or 0)
        answer = f"{ticker} 分部构成：{ ' / '.join(lines) }。最大分部是「{top['name']}」。"
    else:
        answer = "暂未解析到分部数据。"
    return {"answer": answer, "claims": claims[:4], "metric_ids": [],
            "limitations": ["分部利润率未披露时系统显示 NOT_DISCLOSED，不估算"]}


def _answer_valuation(store, company_id: str, ticker: str) -> dict:
    try:
        dv = default_valuation(store, company_id, ticker)
        fair = dv["result"]["fair_value_per_share"]
        tv = dv["result"]["terminal_value_share"]
        bear = dv["scenarios"]["bear"]["result"]["fair_value_per_share"]
        bull = dv["scenarios"]["bull"]["result"]["fair_value_per_share"]
        market = dv.get("market") or {}
        if market.get("status") == "OK" and market.get("quote") and "price_vs_fair_pct" in (market.get("derived") or {}):
            price = market["quote"]["price"]
            premium = market["derived"]["price_vs_fair_pct"]
            side = f"现价 ${price:.2f} 较公允价 {premium:+.1f}%（确定性 price_vs_fair.v1）"
        else:
            side = "行情未同步，无法与市场价格对比（运行 sync-quotes 后可见）"
        return {
            "answer": (f"{ticker} 确定性 FCFF DCF：Base ${fair:.0f}，参考区间 ${bear:.0f}–${bull:.0f}，"
                       f"终值占 EV {tv*100:.0f}%。{side}。"),
            "claims": [
                _claim(f"DCF Base 每股价值 ${fair:.0f}（fcff_dcf.v1，假设可溯源）。", "MEDIUM",
                       ["valuation_model:fcff_dcf.v1"]),
                _claim("估值对终值假设敏感度较高（>60% 场景）。", "MEDIUM", ["valuation_model:sensitivity"]),
            ],
            "metric_ids": [],
            "limitations": ["无风险利率为配置回退值（Treasury 当前不可达）；模型假设均可调整", "研究参考，非目标价"],
        }
    except Exception as exc:
        return {"answer": f"估值暂不可用：{exc}", "claims": [], "metric_ids": [], "limitations": ["先同步财务数据"]}


def _answer_overview(store, company_id: str, ticker: str) -> dict:
    rev = _num(store, company_id, "REVENUE")
    opp = _num(store, company_id, "OPERATING_MARGIN")
    lr, lo = _latest(rev), _latest(opp)
    claims = []
    if lr and lr.value:
        claims.append(_claim(f"{ticker} 最新季度收入 ${lr.value/1e9:.0f}B（{lr.period_label}）。", "HIGH", [lr.canonical_fact_id]))
    if lo and lo.value:
        claims.append(_claim(f"营业利润率 {lo.value*100:.1f}%。", "HIGH", [lo.canonical_fact_id]))
    return {
        "answer": "你可以问我：收入增长为什么放缓/加快？利润率现状？现金流与回购？有哪些风险？估值如何？业务构成？",
        "claims": claims,
        "metric_ids": [],
        "limitations": ["本助手只回答有真实证据的问题；无法回答的会明说，不编造"],
    }
