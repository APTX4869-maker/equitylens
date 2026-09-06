"""Deterministic moat-evidence engine (M8.x / post-M7 follow-up).

A moat claim is ONLY as good as its evidence. This engine reads what SEC data
can support deterministically — multi-year gross/operating margin level and
stability (pricing power proxy), FCF self-funding, capital intensity,
scale, segment/product dependency, board independence where the 14A marks it —
and produces structured signals with evidence ids.

Qualitative dimensions with NO numeric SEC evidence (brand, network effects,
switching costs, intangible/IP strength, customer concentration) are listed
as explicit evidence GAPS and never rated. No aggregate score is invented:
the read is "N strengths, M watch items, K evidence gaps".
"""

from __future__ import annotations

from dataclasses import dataclass

from equitylens.metrics.engine import MetricEngine

MOAT_METHOD = "deterministic-moat-evidence.v1"

# Qualitative dimensions we cannot evidence from SEC numbers alone.
QUALITATIVE_GAPS = [
    ("品牌与用户忠诚度", "品牌溢价需要价格/份额/调研证据，SEC 财报不披露。"),
    ("网络效应 / 生态锁定", "需要用户行为与平台数据，SEC 不披露。"),
    ("转换成本", "需要客户留存/流失数据，SEC 不披露。"),
    ("无形资产与专利强度", "资产负债表上的无形资产不区分竞争性专利与常规商誉。"),
    ("客户集中度风险", "SEC 仅披露重大客户（如占总收入 10%+ 时），未见披露说明不构成客户多元证据。"),
]


@dataclass
class Signal:
    dimension: str
    verdict: str  # strength | watch | concern
    title: str
    detail: str
    evidence_ids: list[str]
    value_label: str | None = None


def _series(engine: MetricEngine, company_id: str, metric: str, freq: str = "annual"):
    try:
        return [p for p in engine.compute(metric, company_id, frequency=freq) if p.value]
    except ValueError:
        return []


def _id(p) -> str | None:
    return p.canonical_fact_id


def _evidence_ids(points) -> list[str]:
    """Evidence IDs for a series: canonical fact id for passthrough facts, or the
    full input lineage for derived metrics (whose own id is None)."""
    ids: list[str] = []
    for p in points:
        if p.canonical_fact_id:
            ids.append(p.canonical_fact_id)
        elif getattr(p, "input_fact_ids", None):
            ids.extend(p.input_fact_ids)
    return ids


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def moat_signals(store, company_id: str, ticker: str) -> dict:
    engine = MetricEngine(store)
    signals: list[Signal] = []
    ev = _evidence_ids

    # ---- 1) pricing power: gross margin level + stability/trend (5Y annual) ----
    gm = _series(engine, company_id, "GROSS_MARGIN", "annual")[-6:]
    if gm:
        vals = [float(p.value) for p in gm]
        level = _mean(vals)
        spread = max(vals) - min(vals) if len(vals) >= 3 else 0.0
        stable = len(vals) >= 4 and spread <= 0.06
        rising = len(vals) >= 2 and vals[-1] - vals[0] >= 0.04
        if level >= 0.30 and (stable or rising):
            verdict = "strength"
            title = ("高且稳定的毛利率（定价权证据）" if stable
                     else "毛利率高且持续抬升（定价权证据）")
        elif level >= 0.30:
            verdict, title = "watch", "毛利率高但波动偏大"
        else:
            verdict, title = "watch", "毛利率水平一般"
        trend = f"，较最早财年{'抬升' if rising else ('回落' if vals[-1] < vals[0] else '持平')}"
        signals.append(Signal(
            "盈利护城河", verdict, title,
            f"近 {len(vals)} 个财年毛利率均值 {level*100:.1f}%，最高-最低 {spread*100:.1f}pp{trend}"
            f"（{'波动 ≤6pp，未见定价权侵蚀' if stable else '注意波动'})。",
            evidence_ids=ev(gm), value_label=f"{level*100:.1f}% (5Y 均值)",
        ))

    # ---- 2) operating leverage/profitability ----
    om = _series(engine, company_id, "OPERATING_MARGIN", "annual")[-6:]
    if om:
        vals = [float(p.value) for p in om]
        latest = vals[-1]
        if latest >= 0.20:
            verdict, title = "strength", "高营业利润率（生意结构）"
        else:
            verdict, title = "watch", "营业利润率承压"
        signals.append(Signal(
            "盈利护城河", verdict, title,
            f"最新财年营业利润率 {latest*100:.1f}%（近 {len(vals)} 财年均值 {_mean(vals)*100:.1f}%）。",
            evidence_ids=ev(om), value_label=f"{latest*100:.1f}% (最新FY)",
        ))

    # ---- 3) self-funding: FCF margin ----
    fcfm = _series(engine, company_id, "FCF_MARGIN", "annual")[-4:]
    if fcfm:
        latest = float(fcfm[-1].value)
        verdict = "strength" if latest >= 0.12 else ("watch" if latest >= 0.05 else "concern")
        title = {
            "strength": "强劲自由现金流（自筹资金）",
            "watch": "自由现金流率中等",
            "concern": "自由现金流率偏低",
        }[verdict]
        signals.append(Signal(
            "现金流护城河", verdict, title,
            f"最新财年 FCF 利润率 {latest*100:.1f}%——无需外部融资即可支持再投资与分红回购。",
            evidence_ids=ev(fcfm), value_label=f"{latest*100:.1f}% (最新FY)",
        ))

    # ---- 4) capital intensity (asset-light vs heavy reinvestment) ----
    rev = _series(engine, company_id, "REVENUE", "annual")[-1:]
    capex = _series(engine, company_id, "CAPITAL_EXPENDITURES", "annual")[-1:]
    if rev and capex and rev[-1].fiscal_year == capex[-1].fiscal_year:
        ratio = float(capex[-1].value) / float(rev[-1].value)
        verdict = "strength" if ratio <= 0.12 else ("watch" if ratio <= 0.25 else "concern")
        title = {
            "strength": "轻资本开支（资产轻）",
            "watch": "资本开支强度中等",
            "concern": "资本开支强度高（再投资回报待验证）",
        }[verdict]
        signals.append(Signal(
            "再投资需求", verdict, title,
            f"FY{capex[-1].fiscal_year} 资本开支占收入 {ratio*100:.1f}%（CapEx ${float(capex[-1].value)/1e9:.0f}B / 收入 ${float(rev[-1].value)/1e9:.0f}B）。",
            evidence_ids=ev(rev) + ev(capex), value_label=f"{ratio*100:.1f}% (最新FY)",
        ))

    # ---- 5) scale ----
    if rev:
        latest = float(rev[-1].value)
        signals.append(Signal(
            "规模", "strength", "绝对规模领先",
            f"FY{rev[-1].fiscal_year} 收入 ${latest/1e9:.0f}B——规模本身是融资成本、分销与研发摊销的护城河。",
            evidence_ids=ev(rev), value_label=f"${latest/1e9:.0f}B (FY{rev[-1].fiscal_year})",
        ))

    # ---- 6) segment/product dependency ----
    dependency_count = 0
    try:
        from equitylens.api.segments_service import get_segments

        for kind, label in (("segment", "分部"), ("product", "产品类别")):
            seg = get_segments(store, ticker, kind=kind, frequency="annual")
            segs = [s for s in seg["segments"] if s.get("share")]
            if not segs:
                continue
            dependency_count += 1
            top = max(segs, key=lambda s: s["share"] or 0)
            share = top["share"] or 0.0
            verdict = "watch" if share >= 0.40 else "strength"
            signals.append(Signal(
                "收入依赖", verdict,
                f"最大{label}占比 {share*100:.0f}%（{'依赖度较高，单点集中' if verdict == 'watch' else '结构相对分散'}）",
                f"{top['name']} 占 FY 收入的 {share*100:.0f}%——{label}级集中度（SEC 分部披露口径）。",
                evidence_ids=[f"segment:{top['name']}"], value_label=f"{share*100:.0f}%",
            ))
    except Exception:
        dependency_count = 0  # segment data unavailable -> honest gap below
    if dependency_count == 0:
        gaps.append({"dimension": "分部/产品收入依赖",
                     "note": "当前数据源没有可用的年度分部披露（运行 sync-segments 后自动评估）；依赖度未判定。"})

    # ---- 7) board independence (only when the 14A marks it) ----
    board = store.query(
        "SELECT independent FROM board_member WHERE company_id = ?", [company_id])
    if board and any(str(b["independent"] or "").strip() for b in board):
        marked = [b for b in board if str(b["independent"] or "").strip()]
        indep = sum(1 for b in marked if str(b["independent"]).lower().startswith("yes") or str(b["independent"]) == "是")
        ratio = indep / len(marked)
        verdict = "strength" if ratio >= 0.75 else "watch"
        signals.append(Signal(
            "治理", verdict,
            f"董事会独立性 {ratio*100:.0f}%",
            f"14A 标注的 {len(marked)} 位董事中 {indep} 位独立（比例 {ratio*100:.0f}%）。",
            evidence_ids=["board_member"], value_label=f"{ratio*100:.0f}%",
        ))

    gaps = [{"dimension": d, "note": n} for d, n in QUALITATIVE_GAPS]
    if not board or not any(str(b["independent"] or "").strip() for b in board):
        gaps.insert(0, {"dimension": "董事会独立性标注",
                        "note": "该 14A 未逐位标注独立性，无法从 SEC 数字证据评估。"})

    n_strength = sum(1 for s in signals if s.verdict == "strength")
    n_watch = sum(1 for s in signals if s.verdict == "watch")
    n_concern = sum(1 for s in signals if s.verdict == "concern")
    summary = (
        f"基于可用 SEC 数字证据（{MOAT_METHOD}）：{n_strength} 项强信号"
        f"{('（' + '、'.join(s.title for s in signals if s.verdict == 'strength')[:60] + '…') if n_strength else ''}）"
        f"，{n_watch} 项观察（{ '、'.join(s.title for s in signals if s.verdict == 'watch')[:60]}），"
        f"{n_concern} 项警示。另有 {len(gaps)} 个定性维度为证据缺口，未参与评估——"
        "护城河结论仅覆盖 SEC 数据能支撑的部分，缺口项需定性证据文件补充。"
    )
    return {
        "ticker": ticker,
        "method": MOAT_METHOD,
        "signals": [s.__dict__ for s in signals],
        "qualitative_gaps": gaps,
        "summary": summary,
        "demo": False,
    }
