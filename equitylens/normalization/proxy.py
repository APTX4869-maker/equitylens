"""DEF 14A proxy statement parser (M6).

Extracts:
- Named Executive Officers + Summary Compensation Table rows
- Board of directors table (name / occupation / age / director since / independence)

Proxy documents are HTML tables with issuer-specific layouts; the parser
locates candidate tables by header keywords, then picks the table with the
most data rows, mapping columns by header keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import html as lh

TITLE_KEYWORDS = ("Chairman", "Chief", "Executive", "President", "Senior", "Vice", "Director", "Officer")


@dataclass
class ProxyExecutive:
    name: str
    title: str | None = None
    compensation: list[dict] = field(default_factory=list)  # per fiscal year


@dataclass
class ProxyDirector:
    name: str
    occupation: str | None = None
    age: int | None = None
    director_since: str | None = None
    independent: str | None = None


@dataclass
class ProxyParseResult:
    executives: list[ProxyExecutive] = field(default_factory=list)
    directors: list[ProxyDirector] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _table_rows(t):
    return [tr for tr in t.iterfind(".//tr")]


def _header_row(rows, max_scan: int = 5):
    for tr in rows[:max_scan]:
        cells = [_norm(c.text_content()) for c in tr.iterfind(".//td")]
        cells = [c for c in cells if c]
        if cells:
            return cells
    return []


def _candidate_tables(doc, keywords: tuple[str, ...]):
    """All tables whose (first non-empty) header row contains all keywords."""
    out = []
    for t in doc.iterfind(".//table"):
        header = _header_row(_table_rows(t))
        joined = " ".join(header).lower()
        if all(k.lower() in joined for k in keywords):
            out.append(t)
    return out


def _split_name_title(cell: str) -> tuple[str, str | None]:
    parts = cell.split(" ")
    for i, w in enumerate(parts):
        if w in TITLE_KEYWORDS:
            name = " ".join(parts[:i]).strip()
            title = " ".join(parts[i:]).strip()
            return name or cell, title or None
    return cell, None


_NUM = re.compile(r"^[\d,]+\.?\d*$")


def _num(cell: str) -> float | None:
    c = cell.replace(",", "").replace("$", "").strip()
    if not c or not _NUM.match(c):
        return None
    return float(c)


def _add_comp_row(executive: ProxyExecutive, cells: list[str]) -> None:
    if not cells or not re.fullmatch(r"\d{4}", cells[0].strip()):
        return
    year = int(cells[0].strip())
    clean = [c for c in cells[1:] if not re.fullmatch(r"\([0-9]+\)+", c.strip())]
    nums = [_num(c) for c in clean if _num(c) is not None]
    if len(nums) < 2:
        return
    row: dict = {"year": year}
    row["salary"] = nums[0]
    if len(nums) >= 3:
        row["stock_awards"] = nums[1]  # AAPL/MSFT both put stock awards 2nd numeric after salary
        row["total"] = nums[-1]
        row["non_equity_incentive"] = nums[-2]
        row["all_other"] = nums[-3]
    executive.compensation.append(row)


def _parse_compensation_table(doc) -> list[ProxyExecutive]:
    candidates = _candidate_tables(doc, ("Principal Position", "Total", "Salary"))
    if not candidates:
        return []
    table = max(candidates, key=lambda t: len(_table_rows(t)))
    execs: list[ProxyExecutive] = []
    current: ProxyExecutive | None = None
    for tr in _table_rows(table):
        cells = [_norm(c.text_content()) for c in tr.iterfind(".//td")]
        # compensation tables interleave an empty cell after every value column
        cells = [c for c in cells if c]
        if not cells:
            continue
        first = cells[0]
        if "Principal Position" in first or ("Year" in first and "Salary" in first):
            continue
        if re.fullmatch(r"\d{4}", first):
            if current is not None:
                _add_comp_row(current, cells)
            continue
        name, title = _split_name_title(first)
        current = ProxyExecutive(name=name, title=title)
        _add_comp_row(current, cells[1:])
        execs.append(current)
    return execs


def _parse_director_table(doc) -> list[ProxyDirector]:
    candidates = _candidate_tables(doc, ("Director Since", "Independent"))
    if not candidates:
        return []
    table = max(candidates, key=lambda t: len(_table_rows(t)))
    raw_header = _header_row(_table_rows(table))
    # Two issuer conventions: MSFT interleaves an empty cell after every value
    # column; AAPL keeps genuinely empty cells (e.g. Independent blank). Detect
    # from the header: if any header cell is empty -> interleave -> filter rows.
    interleaved = any(not c for c in raw_header)

    def row_cells(tr):
        cells = [_norm(c.text_content()) for c in tr.iterfind(".//td")]
        return [c for c in cells if c] if interleaved else cells

    header = row_cells(_table_rows(table)[0]) if False else None
    # recompute header from the same mode
    for tr in _table_rows(table)[:5]:
        cand = row_cells(tr)
        if cand and ("name" in cand[0].lower() or "director since" in " ".join(cand).lower()):
            header = cand
            break
    col_map: dict[str, int] = {}
    for idx, h in enumerate(header):
        hl = h.lower()
        if "name" in hl:
            col_map["name"] = idx
        elif "occupation" in hl:
            col_map["occupation"] = idx
        elif hl == "age" or "age" == hl:
            col_map["age"] = idx
        elif "director since" in hl:
            col_map["since"] = idx
        elif "independent" in hl:
            col_map["independent"] = idx
    if "name" not in col_map:
        return []
    directors: list[ProxyDirector] = []
    for tr in _table_rows(table)[1:]:
        cells = row_cells(tr)
        if len(cells) <= col_map["name"]:
            continue
        name = cells[col_map["name"]]
        if not name or "Name" in name:
            continue
        age = None
        if "age" in col_map and len(cells) > col_map["age"]:
            m = re.search(r"\b([3-9]\d)\b", cells[col_map["age"]])
            if m:
                age = int(m.group(1))
        since = None
        if "since" in col_map and len(cells) > col_map["since"]:
            since = cells[col_map["since"]]
            if not re.fullmatch(r"(19|20)\d{2}|New Nominee.*", since or ""):
                since = None
        directors.append(
            ProxyDirector(
                name=name,
                occupation=cells[col_map["occupation"]] if col_map.get("occupation") is not None and len(cells) > col_map["occupation"] else None,
                age=age,
                director_since=since,
                independent=cells[col_map["independent"]] if col_map.get("independent") is not None and len(cells) > col_map["independent"] else None,
            )
        )
    return directors


def parse_proxy(content: bytes) -> ProxyParseResult:
    doc = lh.fromstring(content)
    result = ProxyParseResult()
    result.executives = _parse_compensation_table(doc)
    result.directors = _parse_director_table(doc)
    if not result.executives:
        result.warnings.append("Summary Compensation Table not found")
    if not result.directors:
        result.warnings.append("Director table not found")
    return result
