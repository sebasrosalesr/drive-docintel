"""Fund identity, period fields and evidence verification."""
from __future__ import annotations

import calendar
import difflib
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Fund
from .schema import Period

_SUFFIX = re.compile(
    r"\b(l\.?p\.?|llc|ltd\.?|limited|inc\.?|plc|fund|master|feeder|the|trust|sicav|ucits|"
    r"(class|series|share\s*class|cl\.?)\s*[a-z0-9-]+|shares?|units?)\b",
    re.I,
)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def norm_fund_name(name: str) -> str:
    s = _SUFFIX.sub(" ", name.lower())      # before punctuation goes: "L.P." is one token here
    s = _PUNCT.sub(" ", s)
    s = _SUFFIX.sub(" ", s)                 # and again for "Class A" left behind a dash
    return _WS.sub(" ", s).strip()


def resolve_fund(session: Session, name: str, manager: str) -> Fund:
    """Match on normalized name or any stored alias; create otherwise. Never lets the model pick ids."""
    norm = norm_fund_name(name) or name.strip().lower()
    fund = session.scalar(select(Fund).where(Fund.name_norm == norm))
    if fund is None:
        for candidate in session.scalars(select(Fund)):
            if norm in {norm_fund_name(a) for a in (candidate.aliases or [])}:
                fund = candidate
                break
    if fund is None:
        fund = Fund(name=name.strip(), name_norm=norm, manager=manager, aliases=[name.strip()])
        session.add(fund)
        session.flush()
    else:
        aliases = list(fund.aliases or [])
        if name.strip() not in aliases:
            aliases.append(name.strip())
            fund.aliases = aliases
        if not fund.manager and manager:
            fund.manager = manager
    return fund


# ---------- periods ----------
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _month_from_label(label: str) -> tuple[int | None, int | None]:
    """('Jan 2026' | 'January' | '2026-01' | '01/2026') → (year, month)."""
    s = label.strip().lower()
    m = re.search(r"(\d{4})-(\d{1,2})$", s)
    if m:
        return int(m[1]), int(m[2])
    m = re.search(r"(\d{1,2})/(\d{4})", s)
    if m:
        return int(m[2]), int(m[1])
    year = None
    ym = re.search(r"(20\d{2}|19\d{2})", s)
    if ym:
        year = int(ym[1])
    else:
        ym2 = re.search(r"['’](\d{2})\b", s)
        if ym2:
            year = 2000 + int(ym2[1])
    for token in re.findall(r"[a-z]+", s):
        if token in _MONTHS:
            return year, _MONTHS[token]
    return year, None


def period_fields(p: Period, as_of: date | None) -> dict:
    """period_type, period_year, period_month, period_start, period_end for storage."""
    start, end = parse_date(p.start), parse_date(p.end)
    year = month = None
    if p.type == "month":
        if end:
            year, month = end.year, end.month
        elif start:
            year, month = start.year, start.month
        else:
            year, month = _month_from_label(p.label)
            if month and not year and as_of:
                year = as_of.year if month <= as_of.month else as_of.year - 1
        if year and month and not start:
            start = date(year, month, 1)
        if year and month and not end:
            end = date(year, month, calendar.monthrange(year, month)[1])
    elif p.type in ("year", "ytd", "quarter"):
        src = end or start
        if src:
            year = src.year
        else:
            y, _ = _month_from_label(p.label)
            year = y or (as_of.year if as_of else None)
        if p.type == "ytd" and not end and as_of:
            end = as_of
            start = start or date(as_of.year, 1, 1)
    else:
        src = end or start
        year = src.year if src else (as_of.year if as_of else None)
        if not end and as_of and p.type in ("1y", "3y", "5y", "since_inception", "point", "other"):
            end = as_of   # a fee or ratio with no stated period is "as of the document"
    return {"period_type": p.type, "period_year": year, "period_month": month, "period_start": start, "period_end": end}


# ---------- evidence ----------
_NORM_MAP = str.maketrans({"−": "-", "–": "-", "—": "-", " ": " ", "’": "'", "“": '"', "”": '"'})


def _norm_text(s: str) -> str:
    s = s.translate(_NORM_MAP).lower()
    s = re.sub(r"\s*%\s*", "%", s)
    s = re.sub(r"\s*\|\s*", " ", s)
    s = re.sub(r"[^\w%.\-()/]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_PAGE_MARK = re.compile(r"^--- (?:page|slide) (\d+) ---$", re.M)
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def page_texts(text: str) -> dict[int, str]:
    """{page number: text} from the '--- page N ---' markers; {} when there are none."""
    marks = list(_PAGE_MARK.finditer(text or ""))
    out: dict[int, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[int(m.group(1))] = text[m.end():end]
    return out


def _fuzzy(ev: str, body: str, threshold: float) -> float:
    window = len(ev)
    if window < 12 or len(body) < window:
        return 0.0
    best = 0.0
    step = max(1, window // 4)
    for i in range(0, max(1, len(body) - window + 1), step):
        r = difflib.SequenceMatcher(None, ev, body[i:i + window]).ratio()
        if r > best:
            best = r
            if best >= threshold:
                break
    return best


def _all_numbers_present(evidence: str, body_norm: str) -> bool:
    """Fuzzy text matches must never forgive a wrong digit: every number in the fragment has to be in the text."""
    nums = [n.replace(",", "") for n in _NUM.findall(evidence)]
    nums = [n for n in nums if any(ch.isdigit() for ch in n)]
    body = body_norm.replace(",", "")
    return all(n in body for n in nums)


def _numbers_match(evidence: str, body_norm: str) -> bool:
    """Tables reflow when extracted: cells land on separate lines. Accept the fragment when nearly all of
    its numbers and at least one real word appear in the text."""
    nums = [n.replace(",", "") for n in _NUM.findall(evidence)]
    nums = [n for n in nums if any(ch.isdigit() for ch in n) and len(n) >= 2]
    if not nums:
        return False
    hits = sum(1 for n in nums if n in body_norm.replace(",", ""))
    words = [w for w in re.findall(r"[a-z]{4,}", evidence.lower())]
    word_ok = not words or any(w in body_norm for w in words)
    return hits / len(nums) >= 0.8 and word_ok


def verify_evidence(evidence: str, text: str, *, scanned: bool = False, page: int = 0, pages: dict[int, str] | None = None) -> tuple[bool, str]:
    """(verified, note). Tries the cited page first, then the whole text: exact normalized substring,
    fuzzy >= 0.85 on a sliding window, then a numbers-and-a-word match for reflowed table rows."""
    if scanned or not (text or "").strip():
        return False, "scanned" if scanned else "no-text"
    ev = _norm_text(evidence)
    if not ev:
        return False, "empty"
    # "A ... B": the model joined two fragments that sit apart on the page; check each piece
    pieces = [x.strip() for x in re.split(r"\.{3}|\u2026", evidence) if len(x.strip()) >= 6]
    if len(pieces) > 1:
        results = [verify_evidence(x, text, scanned=scanned, page=page, pages=pages) for x in pieces]
        if all(ok for ok, _ in results):
            return True, "pieces"
    candidates: list[str] = []
    page_body = (pages or {}).get(page, "") if page else ""
    if page and pages is not None and page in pages and not page_body.strip():
        return False, "image-page"
    if page_body.strip():
        candidates.append(_norm_text(page_body))
    candidates.append(_norm_text(text))
    for body in candidates:
        if ev in body:
            return True, "exact"
    for body in candidates:
        r = _fuzzy(ev, body, 0.85)
        if r >= 0.85 and _all_numbers_present(evidence, body):
            return True, f"fuzzy {r:.2f}"
    for body in candidates:
        if _numbers_match(evidence, body):
            return True, "numbers"
    return False, "not-found"
