"""Local PII gate. Runs on the extracted text (or OCR) before anything leaves the machine.

Two outcomes:
- identity document (driver's licence, passport, ID card, Social Security card, birth certificate):
  the file is rejected, never sent to the model, and its content is not kept.
- sensitive identifiers inside an ordinary document (SSN/ITIN, card numbers, bank account and
  routing numbers): they are masked and the model receives the masked text instead of the original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

IDENTITY_TERMS: dict[str, tuple[str, list[str]]] = {
    "driver": ("driver's licence", [
        r"driver'?s? licen[cs]e", r"driving licen[cs]e", r"operator'?s? licen[cs]e", r"commercial driver", r"\bdl\s*(?:no|#|number)\b", r"\blic(?:ense|ence)?\s*(?:no|#|number)\b",
        r"\bclass\s*[a-z]\b", r"\bendorsements?\b", r"\brestrictions?\b", r"\bhgt\b", r"\bwgt\b", r"\beyes\b", r"\bhair\b", r"\bsex\s*[:\-]?\s*[mfx]\b",
        r"\biss(?:ued)?\s*[:\-]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", r"\bexp(?:ires|iry)?\s*[:\-]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", r"\bdob\b", r"date of birth",
        r"organ donor", r"\breal id\b", r"\bdmv\b", r"department of motor vehicles", r"\bdonor\b", r"\bveteran\b", r"\b\d\s*'\s*-?\s*\d{1,2}\s*\"",
    ]),
    "passport": ("passport", [r"\bpassport\b", r"passport\s*(?:no|#|number)", r"\bnationality\b", r"place of birth", r"date of issue", r"date of expir", r"\bp<[a-z]{3}", r"\btype\s*p\b", r"\bauthority\b", r"\bsurname\b", r"given names?"]),
    "ssn_card": ("Social Security card", [r"social security", r"social security administration", r"this number has been established for", r"signature of the person", r"not valid for employment"]),
    "id_card": ("identity card", [r"identification card", r"identity card", r"national id", r"resident card", r"green card", r"permanent resident", r"uscis\s*#?", r"alien registration", r"birth certificate", r"certificate of live birth", r"\bid\s*(?:no|#|number)\b"]),
}
THRESHOLDS = {"driver": 4, "passport": 3, "ssn_card": 2, "id_card": 2}
SHORT_DOC_CHARS = 6000        # identity documents are a page or two; long documents only count with a very high score
FILENAME_HINTS = re.compile(r"(driver|licen[cs]e|\bdl\b|passport|\bssn\b|social.?security|\bid\b|identity|green.?card|birth.?cert)", re.I)

SSN = re.compile(r"\b(?!000|666|9\d{2})\d{3}[-\s](?!00)\d{2}[-\s](?!0000)\d{4}\b")
ITIN = re.compile(r"\b9\d{2}[-\s][7-9]\d[-\s]\d{4}\b")
SSN_LABELLED = re.compile(r"(?:ssn|social security(?: number| no\.?)?|ss#)\s*[:#]?\s*(\d{3}[-\s]?\d{2}[-\s]?\d{4})", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
ROUTING = re.compile(r"(routing|aba|rtn)\s*(?:no\.?|#|number)?\s*[:#]?\s*(\d{9})\b", re.I)
ACCOUNT = re.compile(r"(account|acct\.?|a/c)\s*(?:no\.?|#|number)?\s*[:#]?\s*(\d[\d\- ]{6,20}\d)\b", re.I)


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class Screen:
    identity: str = ""                 # category key when the document is an identity document
    identity_label: str = ""
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    redacted_text: str = ""
    redactions: dict[str, int] = field(default_factory=dict)

    @property
    def n_redactions(self) -> int:
        return sum(self.redactions.values())


def identity_scores(text: str, name: str = "") -> tuple[dict[str, int], dict[str, list[str]]]:
    low = (text or "").lower()
    scores, hits = {}, {}
    for key, (_, patterns) in IDENTITY_TERMS.items():
        found = []
        for pat in patterns:
            m = re.search(pat, low)
            if m:
                found.append(" ".join(m.group(0).split())[:24])   # the words that matched, for a readable reason
        scores[key] = len(found)
        hits[key] = found
    if name and FILENAME_HINTS.search(name):
        for key in scores:
            scores[key] += 1
    return scores, hits


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    def bump(k: str) -> None:
        counts[k] = counts.get(k, 0) + 1

    def sub_ssn(m: re.Match) -> str:
        bump("ssn")
        return "[REDACTED SSN]"

    def sub_ssn_lab(m: re.Match) -> str:
        bump("ssn")
        return m.group(0)[: m.start(1) - m.start(0)] + "[REDACTED SSN]"

    def sub_card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits) and len(set(digits)) >= 2:
            bump("card")
            return f"[CARD ••••{digits[-4:]}]"
        return m.group(0)

    def sub_routing(m: re.Match) -> str:
        bump("routing")
        return f"{m.group(1)} [ROUTING ••••{m.group(2)[-4:]}]"

    def sub_account(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(2))
        if len(digits) < 8:
            return m.group(0)
        bump("account")
        return f"{m.group(1)} [ACCOUNT ••••{digits[-4:]}]"

    out = SSN_LABELLED.sub(sub_ssn_lab, text or "")
    out = ITIN.sub(sub_ssn, out)
    out = SSN.sub(sub_ssn, out)
    out = CARD.sub(sub_card, out)
    out = ROUTING.sub(sub_routing, out)
    out = ACCOUNT.sub(sub_account, out)
    return out, counts


def screen(text: str, name: str = "") -> Screen:
    scores, hits = identity_scores(text, name)
    s = Screen(scores=scores)
    length = len((text or "").strip())
    best = max(scores, key=lambda k: scores[k] - THRESHOLDS[k]) if scores else ""
    if best and scores[best] >= THRESHOLDS[best] and (length < SHORT_DOC_CHARS or scores[best] >= THRESHOLDS[best] + 4):
        s.identity = best
        s.identity_label = IDENTITY_TERMS[best][0]
        s.reasons = hits[best][:5]
    s.redacted_text, s.redactions = redact(text or "")
    return s
