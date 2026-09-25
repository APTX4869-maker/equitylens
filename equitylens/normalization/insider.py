"""Form 4 (statement of changes in beneficial ownership) parser.

Form 4 filings are XML ownership documents. We extract reporting owner info
and each non-derivative transaction (sales, purchases, exercises, grants).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

OWN_NS = "http://www.sec.gov/edgar/common"


@dataclass
class InsiderTransaction:
    insider_name: str
    insider_cik: str | None
    officer_title: str | None
    transaction_date: str | None
    transaction_code: str | None
    security_title: str | None
    shares: float | None
    price_per_share: float | None
    acquired_disposed_code: str | None
    shares_owned_after: float | None
    footnotes: str | None = None

    @property
    def is_officer(self) -> bool:
        return bool(self.officer_title)


@dataclass
class Form4ParseResult:
    owner_name: str | None = None
    owner_cik: str | None = None
    transactions: list[InsiderTransaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(el, tag: str) -> str | None:
    if el is None:
        return None
    found = el.find(f".//{{{OWN_NS}}}{tag}")
    if found is None:
        found = el.find(f".//{tag}")  # some form4.xml files are un-namespaced
    if found is None:
        return None
    raw = found.text
    # values often sit in a <value> child (transactionDate <value>...)
    if raw is None or not raw.strip():
        child = found.find(f"{{{OWN_NS}}}value")
        if child is None:
            child = found.find("value")
        if child is not None:
            raw = child.text
    return re.sub(r"\s+", " ", (raw or "")).strip() or None


def _num(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_form4(content: bytes) -> Form4ParseResult:
    parser = etree.XMLParser(recover=True)
    root = etree.fromstring(content, parser)
    result = Form4ParseResult()
    result.owner_name = _text(root, "rptOwnerName")
    result.owner_cik = _text(root, "rptOwnerCik")
    owner = root.find(f".//{{{OWN_NS}}}reportingOwner")
    if owner is None:
        owner = root.find(".//reportingOwner")
    title = None
    if owner is not None:
        title = _text(owner, "officerTitle")

    txs = list(root.iter(f"{{{OWN_NS}}}nonDerivativeTransaction"))
    if not txs:
        txs = list(root.iter("nonDerivativeTransaction"))
    for tx in txs:
        t = InsiderTransaction(
            insider_name=result.owner_name,
            insider_cik=result.owner_cik,
            officer_title=title or _text(tx, "officerTitle"),
            transaction_date=_text(tx, "transactionDate"),
            transaction_code=_text(tx, "transactionCode"),
            security_title=_text(tx, "securityTitle"),
            shares=_num(_text(tx, "transactionShares")),
            price_per_share=_num(_text(tx, "transactionPricePerShare")),
            acquired_disposed_code=_text(tx, "transactionAcquiredDisposedCode"),
            shares_owned_after=_num(_text(tx, "sharesOwnedFollowingTransaction")),
        )
        if t.transaction_code or t.shares is not None:
            result.transactions.append(t)
    if not result.transactions:
        result.warnings.append("no non-derivative transactions found")
    return result
