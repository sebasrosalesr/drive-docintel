#!/usr/bin/env python
"""Generate a synthetic, deliberately inconsistent corpus of fund documents plus an answer key.

Five fictional managers, each with its own layout and vocabulary:
  Northwind Capital      table-heavy factsheet (2 share classes), an older edition, and a long CSV with 2025+2026
  Harbor Point Partners  prose investor letter, a quarterly performance report with a benchmark, an HTML email
  Sable Ridge AM         two-column factsheet with a wide month grid, and a wide CSV
  Meridian Quant         image-only ("scanned") factsheet
  Cobalt Row Advisors    account statement with statement vocabulary
Plus one non-financial distractor PDF. Nothing here is real.

  python scripts/make_corpus.py --out corpus
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import random
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AS_OF = date(2026, 9, 30)
MONTHS_2026 = [f"2026-{m:02d}" for m in range(1, 10)]
MONTHS_2025 = [f"2025-{m:02d}" for m in range(1, 13)]
MON = {i: calendar.month_abbr[i] for i in range(1, 13)}

rng = random.Random(20261026)


def series(mean: float, vol: float, n: int, fixed: dict[int, float] | None = None) -> list[float]:
    out = [round(rng.gauss(mean, vol), 2) for _ in range(n)]
    for i, v in (fixed or {}).items():
        out[i] = v
    return out


# ---- the truth (fixed Januaries so "best January" has a known answer) ----
FUNDS = {
    "Northwind Global Macro Fund LP": {
        "manager": "Northwind Capital Management", "strategy": "Global Macro", "currency": "USD",
        "classes": {"Class A": series(0.6, 1.6, 9, {0: 2.14}), "Class I": None},  # I = A + 0.08/month
        "r2025": series(0.5, 1.7, 12, {0: 4.10}),
        "aum": 412_500_000, "mgmt_fee": 1.5, "perf_fee": 20.0, "sharpe": 1.21, "vol": 6.8, "mdd": -4.9,
    },
    "Harbor Point Credit Opportunities Fund": {
        "manager": "Harbor Point Partners", "strategy": "Credit Long/Short", "currency": "USD",
        "classes": {"": series(0.7, 0.9, 9, {0: 0.92})},
        "aum": 1_180_000_000, "mgmt_fee": 1.25, "perf_fee": 15.0, "sharpe": 1.65, "vol": 3.9, "mdd": -2.1,
        "benchmark": "Bloomberg US High Yield Index", "bench": series(0.5, 1.1, 9, {0: 0.61}),
    },
    "Sable Ridge Equity Long/Short": {
        "manager": "Sable Ridge Asset Management", "strategy": "Equity Long/Short", "currency": "USD",
        "classes": {"": series(0.9, 2.4, 9, {0: 3.87})},
        "aum": 268_000_000, "mgmt_fee": 2.0, "perf_fee": 20.0, "sharpe": 0.98, "vol": 9.4, "mdd": -7.3,
    },
    "Meridian Systematic Trend Fund": {
        "manager": "Meridian Quant", "strategy": "Managed Futures / Trend", "currency": "USD",
        "classes": {"": series(0.3, 2.8, 9, {0: -1.35})},
        "aum": 95_300_000, "mgmt_fee": 1.0, "perf_fee": 20.0, "sharpe": 0.41, "vol": 12.1, "mdd": -9.8,
    },
    "Cobalt Row Multi-Strategy Fund": {
        "manager": "Cobalt Row Advisors", "strategy": "Multi-Strategy", "currency": "USD",
        "classes": {"": series(0.5, 0.8, 9, {0: 1.02})},
        "aum": 740_000_000, "mgmt_fee": 1.75, "perf_fee": 17.5, "sharpe": 1.4, "vol": 4.2, "mdd": -2.6,
        "printed_months": ["2026-09"], "printed_stats": ["aum_usd", "mgmt_fee_pct", "perf_fee_pct"],  # the statement prints only these
    },
}
nw = FUNDS["Northwind Global Macro Fund LP"]["classes"]
nw["Class I"] = [round(v + 0.08, 2) for v in nw["Class A"]]


def compound(vals: list[float]) -> float:
    c = 1.0
    for v in vals:
        c *= 1 + v / 100
    return round((c - 1) * 100, 2)


def pct(v: float, paren: bool = False) -> str:
    if paren and v < 0:
        return f"({abs(v):.2f})"
    return f"{v:+.2f}%" if not paren else f"{v:.2f}"


def money(v: float) -> str:
    return f"${v/1e6:,.1f}m" if v < 1e9 else f"${v/1e9:,.2f}bn"


# ---------- PDF helpers ----------
def styles(font="Helvetica"):
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName=font + ("-Bold" if font != "Times-Roman" else ""), fontSize=16, spaceAfter=6, alignment=0),
        "h": ParagraphStyle("h", parent=ss["Heading3"], fontName=font, fontSize=10.5, textColor=colors.HexColor("#1b2a4a"), spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("b", parent=ss["BodyText"], fontName=font, fontSize=8.8, leading=12),
        "small": ParagraphStyle("s", parent=ss["BodyText"], fontName=font, fontSize=7, leading=9, textColor=colors.grey),
    }


def grid(data, font="Helvetica", header_bg="#1b2a4a", size=8):
    t = Table(data, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font, size),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ced6")),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def build(path: Path, story, pagesize=A4):
    SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm).build(story)


# ---------- 1. Northwind: table-heavy factsheet, two editions ----------
def northwind_factsheet(out: Path, through_month: int, filename: str):
    f = FUNDS["Northwind Global Macro Fund LP"]
    st = styles("Helvetica")
    as_of = date(2026, through_month, calendar.monthrange(2026, through_month)[1])
    story = [Paragraph("NORTHWIND CAPITAL MANAGEMENT", st["small"]),
             Paragraph("Northwind Global Macro Fund LP — Monthly Factsheet", st["title"]),
             Paragraph(f"Data as of {as_of.strftime('%d %B %Y')}. Net of all fees. Strategy: {f['strategy']}.", st["body"]),
             Spacer(1, 6), Paragraph("Monthly net performance 2026 (%)", st["h"])]
    head = ["Share class"] + [MON[i] for i in range(1, through_month + 1)] + ["YTD"]
    rows = [head]
    for cls, vals in f["classes"].items():
        v = vals[:through_month]
        rows.append([cls] + [f"{x:.2f}" for x in v] + [f"{compound(v):.2f}"])
    story += [grid(rows), Spacer(1, 8), Paragraph("Key statistics (Class A, since inception Jan 2021)", st["h"])]
    stats = [["Metric", "Value"], ["Fund AUM", money(f["aum"])], ["Management fee", f"{f['mgmt_fee']:.2f}% p.a."],
             ["Performance fee", f"{f['perf_fee']:.0f}%"], ["Sharpe ratio (ann.)", f"{f['sharpe']:.2f}"],
             ["Annualised volatility", f"{f['vol']:.1f}%"], ["Maximum drawdown", f"{f['mdd']:.1f}%"],
             ["1 year return (net)", f"{compound(f['r2025'][through_month:] + f['classes']['Class A'][:through_month]):.2f}%"]]
    story += [grid(stats), Spacer(1, 8),
              Paragraph("Calendar year 2025 net return, Class A: " + f"{compound(f['r2025']):.2f}%.", st["body"]),
              Spacer(1, 10), Paragraph("For professional investors only. Past performance is not a reliable indicator of future results. TEST MATERIAL — fictional.", st["small"])]
    build(out / filename, story)


def northwind_csv(out: Path):
    f = FUNDS["Northwind Global Macro Fund LP"]
    lines = ["date,fund,share_class,net_return_pct"]
    for i, m in enumerate(MONTHS_2025):
        lines.append(f"{m}-{calendar.monthrange(2025, i+1)[1]},Northwind Global Macro Fund LP,Class A,{f['r2025'][i]:.2f}")
    for cls, vals in f["classes"].items():
        for i, m in enumerate(MONTHS_2026):
            lines.append(f"{m}-{calendar.monthrange(2026, i+1)[1]},Northwind Global Macro Fund LP,{cls},{vals[i]:.2f}")
    (out / "northwind_monthly_returns_long.csv").write_text("\n".join(lines) + "\n")


# ---------- 2. Harbor Point: prose letter + quarterly report + HTML email ----------
def harbor_letter(out: Path):
    f = FUNDS["Harbor Point Credit Opportunities Fund"]
    v = f["classes"][""]
    st = styles("Times-Roman")
    q3 = compound(v[6:9])
    story = [Paragraph("Harbor Point Partners", st["title"]),
             Paragraph("Credit Opportunities Fund — Investor Letter, September 2026", st["h"]),
             Paragraph(f"Dear Partners,", st["body"]), Spacer(1, 4),
             Paragraph(f"The Harbor Point Credit Opportunities Fund returned {v[8]:+.2f}% net in September and {q3:+.2f}% for the third quarter, bringing year-to-date net performance to {compound(v):+.2f}% as of 30 September 2026. Over the same period the {f['benchmark']} returned {compound(f['bench']):+.2f}%.", st["body"]), Spacer(1, 4),
             Paragraph(f"Monthly net returns this year were: January {v[0]:+.2f}%, February {v[1]:+.2f}%, March {v[2]:+.2f}%, April {v[3]:+.2f}%, May {v[4]:+.2f}%, June {v[5]:+.2f}%, July {v[6]:+.2f}%, August {v[7]:+.2f}% and September {v[8]:+.2f}%.", st["body"]), Spacer(1, 4),
             Paragraph(f"Assets under management stood at {money(f['aum'])} at quarter end. The fund charges a {f['mgmt_fee']:.2f}% management fee and a {f['perf_fee']:.0f}% incentive fee over a hurdle. Realised volatility since inception is {f['vol']:.1f}% with a Sharpe ratio of {f['sharpe']:.2f}; the largest peak-to-trough drawdown was {f['mdd']:.1f}%.", st["body"]), Spacer(1, 4),
             Paragraph("We remain constructive on senior secured paper and continue to avoid CCC-rated issuers. Thank you for your continued trust.", st["body"]), Spacer(1, 8),
             Paragraph("Sincerely,<br/>The Harbor Point Investment Team", st["body"]), Spacer(1, 14),
             Paragraph("Confidential. For existing limited partners only. TEST MATERIAL — fictional.", st["small"])]
    build(out / "HarborPoint_Investor_Letter_Sep2026.pdf", story, pagesize=letter)


def harbor_quarterly(out: Path):
    f = FUNDS["Harbor Point Credit Opportunities Fund"]
    v, b = f["classes"][""], f["bench"]
    st = styles("Helvetica")
    rows = [["Month", "Fund (net)", f["benchmark"], "Excess"]]
    for i in range(6, 9):
        rows.append([f"{MON[i+1]} 2026", f"{v[i]:.2f}%", f"{b[i]:.2f}%", f"{v[i]-b[i]:+.2f}%"])
    rows.append(["Q3 2026", f"{compound(v[6:9]):.2f}%", f"{compound(b[6:9]):.2f}%", f"{compound(v[6:9])-compound(b[6:9]):+.2f}%"])
    rows.append(["YTD 2026", f"{compound(v):.2f}%", f"{compound(b):.2f}%", f"{compound(v)-compound(b):+.2f}%"])
    story = [Paragraph("Harbor Point Partners · Quarterly Performance Report", st["title"]),
             Paragraph("Harbor Point Credit Opportunities Fund · Q3 2026 (period ending 30 Sep 2026)", st["h"]),
             grid(rows, header_bg="#2f4f4f"), Spacer(1, 8),
             Paragraph("Gross returns for the quarter were approximately 0.35% higher than net. All figures in USD. TEST MATERIAL — fictional.", st["small"])]
    build(out / "HarborPoint_Q3_2026_Performance_Report.pdf", story)


def harbor_email(out: Path):
    f = FUNDS["Harbor Point Credit Opportunities Fund"]
    v = f["classes"][""]
    html = f"""<html><head><style>body{{font-family:Arial;font-size:13px;color:#222}} table{{border-collapse:collapse}} td,th{{border:1px solid #bbb;padding:4px 8px}}</style></head>
<body><p><b>From:</b> ir@harborpoint.example &nbsp; <b>Subject:</b> Harbor Point Credit Opportunities — September 2026 flash estimate</p>
<p>Dear investor,</p>
<p>The flash estimate for <b>September 2026</b> is <b>{v[8]:+.2f}%</b> net (YTD {compound(v):+.2f}%). Final figures will follow with the monthly factsheet.</p>
<table><tr><th>Period</th><th>Net return</th></tr>
<tr><td>Sep 2026 (estimate)</td><td>{v[8]:.2f}%</td></tr>
<tr><td>Aug 2026</td><td>{v[7]:.2f}%</td></tr>
<tr><td>Jul 2026</td><td>{v[6]:.2f}%</td></tr>
<tr><td>YTD 2026</td><td>{compound(v):.2f}%</td></tr></table>
<p>Estimated AUM at month end: {money(f['aum'])}.</p>
<p>Kind regards,<br>Investor Relations, Harbor Point Partners<br><i>TEST MATERIAL — fictional.</i></p></body></html>"""
    (out / "HarborPoint_Sep2026_flash_email.html").write_text(html)


# ---------- 3. Sable Ridge: two-column with a wide grid + wide CSV ----------
def sable_factsheet(out: Path):
    f = FUNDS["Sable Ridge Equity Long/Short"]
    v = f["classes"][""]
    st = styles("Helvetica")
    left = [Paragraph("Sable Ridge Asset Management", st["h"]),
            Paragraph("Sable Ridge Equity Long/Short", st["title"]),
            Paragraph("Fund overview as at 30/09/2026", st["body"]), Spacer(1, 6),
            grid([["Fund facts", ""], ["Strategy", f["strategy"]], ["Net assets", f"USD {f['aum']/1e6:,.0f} million"],
                  ["Mgmt fee / Perf fee", f"{f['mgmt_fee']:.2f}% / {f['perf_fee']:.0f}%"],
                  ["Volatility (ann.)", f"{f['vol']:.1f}%"], ["Sharpe", f"{f['sharpe']:.2f}"], ["Max drawdown", f"{f['mdd']:.1f}%"]], header_bg="#5a4634")]
    perf = [["Performance (%)"] + [MON[i] for i in range(1, 10)] + ["YTD"],
            ["2026 net"] + [pct(x, paren=True) for x in v] + [pct(compound(v), paren=True)]]
    right = [Paragraph("Performance (%, net, parentheses = negative)", st["h"]), grid(perf, size=6.5, header_bg="#5a4634"), Spacer(1, 6),
             Paragraph("The fund runs a concentrated book of 25–35 longs against a diversified short book. Gross exposure averaged 165% in Q3.", st["body"]),
             Spacer(1, 6), Paragraph("TEST MATERIAL — fictional.", st["small"])]
    two_col = Table([[left, right]], colWidths=[7.5 * cm, 10.2 * cm])
    two_col.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    build(out / "SableRidge_LS_Factsheet_2026-09.pdf", [two_col])


def sable_csv(out: Path):
    f = FUNDS["Sable Ridge Equity Long/Short"]
    v = f["classes"][""]
    head = "Fund," + ",".join(f"{MON[i]}-26" for i in range(1, 10)) + ",YTD"
    row = "Sable Ridge Equity Long/Short," + ",".join(f"{x:.2f}" for x in v) + f",{compound(v):.2f}"
    (out / "sable_ridge_performance_2026_wide.csv").write_text("# Sable Ridge AM - net monthly performance, percent\n" + head + "\n" + row + "\n")


# ---------- 4. Meridian: image-only PDF ----------
def meridian_scanned(out: Path):
    f = FUNDS["Meridian Systematic Trend Fund"]
    v = f["classes"][""]
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), (250, 248, 243))
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 40)
        med = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except OSError:
        big = ImageFont.load_default(size=40)
        med = ImageFont.load_default(size=28)
    y = 90
    for line, font in [("MERIDIAN QUANT", med), ("Meridian Systematic Trend Fund", big), ("Monthly report  |  30 September 2026", med), ("", med),
                       ("Net monthly performance 2026", med)]:
        d.text((90, y), line, fill=(20, 20, 30), font=font)
        y += 58
    for i, x in enumerate(v):
        d.text((110, y), f"{MON[i+1]} 2026", fill=(20, 20, 30), font=med)
        d.text((520, y), f"{x:+.2f} %", fill=(20, 20, 30), font=med)
        y += 44
    d.text((110, y), "YTD 2026", fill=(20, 20, 30), font=med)
    d.text((520, y), f"{compound(v):+.2f} %", fill=(20, 20, 30), font=med)
    y += 90
    for line in [f"Assets under management: USD {f['aum']/1e6:.1f} million", f"Management fee {f['mgmt_fee']:.2f}%  Performance fee {f['perf_fee']:.0f}%",
                 f"Annualised volatility {f['vol']:.1f}%   Sharpe ratio {f['sharpe']:.2f}   Max drawdown {f['mdd']:.1f}%",
                 "Trend-following across 70 futures markets. TEST MATERIAL - fictional."]:
        d.text((110, y), line, fill=(20, 20, 30), font=med)
        y += 46
    img = img.rotate(0.6, fillcolor=(250, 248, 243))  # a slightly skewed "scan"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    buf.seek(0)
    build(out / "Meridian_Trend_Sep2026_scan.pdf", [RLImage(buf, width=17.5 * cm, height=17.5 * cm * H / W)])


# ---------- 5. Cobalt Row: account statement ----------
def cobalt_statement(out: Path):
    f = FUNDS["Cobalt Row Multi-Strategy Fund"]
    v = f["classes"][""]
    st = styles("Courier")
    units = 12_480.5512
    nav_end = 1_312.4471
    q3 = compound(v[6:9])
    nav_begin = round(nav_end / (1 + q3 / 100), 4)
    story = [Paragraph("COBALT ROW ADVISORS LLC — STATEMENT OF ACCOUNT", st["title"]),
             Paragraph("Investor: Example Family Office LP · Account 44-0192 · Period: 01 Jul 2026 to 30 Sep 2026", st["body"]), Spacer(1, 8),
             grid([["Holding", "Units", "NAV per unit (30 Sep 2026)", "Market value"],
                   ["Cobalt Row Multi-Strategy Fund", f"{units:,.4f}", f"{nav_end:,.4f}", f"${units*nav_end:,.2f}"]], font="Courier", header_bg="#333"),
             Spacer(1, 8),
             grid([["Activity summary", "Amount"], ["Beginning balance (01 Jul 2026)", f"${units*nav_begin:,.2f}"], ["Contributions", "$0.00"], ["Withdrawals", "$0.00"],
                   ["Net investment result", f"${units*(nav_end-nav_begin):,.2f}"], ["Ending balance (30 Sep 2026)", f"${units*nav_end:,.2f}"]], font="Courier", header_bg="#333"),
             Spacer(1, 8),
             Paragraph(f"Period performance (net of fees): {q3:+.2f}% for the quarter; {compound(v):+.2f}% year to date; September {v[8]:+.2f}%.", st["body"]),
             Paragraph(f"Fund net assets at period end: {money(f['aum'])}. Fees: {f['mgmt_fee']:.2f}% management, {f['perf_fee']:.1f}% incentive.", st["body"]),
             Spacer(1, 10), Paragraph("Statements are produced by the administrator. TEST MATERIAL — fictional.", st["small"])]
    build(out / "CobaltRow_Statement_Q3_2026.pdf", story, pagesize=letter)


# ---------- 6. Word memo (Northwind) and Excel workbook (Meridian) ----------
def northwind_docx(out: Path):
    from docx import Document as Docx
    f = FUNDS["Northwind Global Macro Fund LP"]
    a, i_ = f["classes"]["Class A"], f["classes"]["Class I"]
    d = Docx()
    d.add_heading("Northwind Capital Management", 1)
    d.add_heading("Global Macro Fund LP: Q3 2026 investor update", 2)
    d.add_paragraph("Dear investor, this note summarises the third quarter of 2026 for the Northwind Global Macro Fund LP, with figures as of 30 September 2026 and net of all fees.")
    d.add_paragraph(f"The fund returned {compound(a[6:9]):+.2f}% in the quarter for Class A ({compound(i_[6:9]):+.2f}% for Class I), taking the year-to-date net return to {compound(a):+.2f}% and {compound(i_):+.2f}% respectively.")
    t = d.add_table(rows=1, cols=4)
    t.style = "Light Grid Accent 1"
    hdr = t.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = "Month", "Class A (net %)", "Class I (net %)", "Comment"
    for idx, note in zip(range(6, 9), ["Rates book detracted", "Strong FX carry", "De-risked into month end"]):
        r = t.add_row().cells
        r[0].text, r[1].text, r[2].text, r[3].text = f"{MON[idx+1]} 2026", f"{a[idx]:.2f}", f"{i_[idx]:.2f}", note
    d.add_paragraph(f"Assets under management were {money(f['aum'])} at quarter end. Terms are unchanged: {f['mgmt_fee']:.2f}% management fee and a {f['perf_fee']:.0f}% performance fee above the high-water mark.")
    d.add_paragraph("TEST MATERIAL. Fictional manager and figures.").italic = True
    d.save(str(out / "Northwind_Q3_2026_Investor_Update.docx"))


def meridian_xlsx(out: Path):
    from openpyxl import Workbook
    f = FUNDS["Meridian Systematic Trend Fund"]
    v = f["classes"][""]
    wb = Workbook()
    ws = wb.active
    ws.title = "Performance"
    ws.append(["Meridian Systematic Trend Fund", "", ""])
    ws.append(["Net monthly performance 2026 (%)", "", ""])
    ws.append([])
    ws.append(["Month", "Net return %", "Cumulative %"])
    cum = 1.0
    for idx, x in enumerate(v):
        cum *= 1 + x / 100
        ws.append([f"{MON[idx+1]}-2026", x, round((cum - 1) * 100, 2)])
    ws.append(["YTD", compound(v), ""])
    ws2 = wb.create_sheet("Terms")
    ws2.append(["Item", "Value"])
    ws2.append(["Manager", "Meridian Quant"])
    ws2.append(["AUM (USD)", f["aum"]])
    ws2.append(["Management fee", f"{f['mgmt_fee']:.2f}%"])
    ws2.append(["Performance fee", f"{f['perf_fee']:.0f}%"])
    ws2.append(["As of", "2026-09-30"])
    ws2.append(["Note", "TEST MATERIAL - fictional"])
    wb.save(str(out / "Meridian_Trend_2026_monthly.xlsx"))


# ---------- 7. distractor ----------
def distractor(out: Path):
    st = styles("Helvetica")
    build(out / "Office_Holiday_Schedule_2027.pdf", [Paragraph("Office holiday schedule 2027", st["title"]),
          Paragraph("1 Jan New Year's Day · 19 Jan MLK Day · 25 May Memorial Day · 3 Jul Independence Day (observed) · 7 Sep Labor Day · 26 Nov Thanksgiving · 25 Dec Christmas.", st["body"])])


def answer_key() -> dict:
    key = {"as_of": AS_OF.isoformat(), "funds": {}, "questions": []}
    for name, f in FUNDS.items():
        entry = {"manager": f["manager"], "strategy": f["strategy"], "aum_usd": f["aum"], "mgmt_fee_pct": f["mgmt_fee"],
                 "perf_fee_pct": f["perf_fee"], "sharpe": f["sharpe"], "volatility_pct": f["vol"], "max_drawdown_pct": f["mdd"], "classes": {}}
        for cls, vals in f["classes"].items():
            entry["classes"][cls or "(none)"] = {"monthly_net_pct_2026": dict(zip(MONTHS_2026, vals)), "ytd_2026_pct": compound(vals)}
        if "r2025" in f:
            entry["classes"]["Class A"]["monthly_net_pct_2025"] = dict(zip(MONTHS_2025, f["r2025"]))
        if "printed_months" in f:
            entry["printed_months"] = f["printed_months"]
        if "printed_stats" in f:
            entry["printed_stats"] = f["printed_stats"]
        if "bench" in f:
            entry["benchmark"] = {"name": f["benchmark"], "monthly_pct_2026": dict(zip(MONTHS_2026, f["bench"]))}
        key["funds"][name] = entry
    best26 = max(FUNDS, key=lambda n: FUNDS[n]["classes"][next(iter(FUNDS[n]["classes"]))][0])
    key["questions"] = [
        {"q": "Which fund had the best January return?",
         "a": f"January 2026: {best26} ({FUNDS[best26]['classes'][next(iter(FUNDS[best26]['classes']))][0]:+.2f}%). "
              f"If January 2025 is included (Northwind CSV only): Northwind Class A {FUNDS['Northwind Global Macro Fund LP']['r2025'][0]:+.2f}%. A good answer states the year."},
        {"q": "What is Harbor Point's YTD return versus its benchmark?",
         "a": f"{compound(FUNDS['Harbor Point Credit Opportunities Fund']['classes'][''])}% vs {compound(FUNDS['Harbor Point Credit Opportunities Fund']['bench'])}% (Bloomberg US High Yield)."},
        {"q": "Which manager charges the highest management fee?", "a": "Sable Ridge Asset Management, 2.00%."},
        {"q": "Total AUM across all funds?", "a": f"${sum(f['aum'] for f in FUNDS.values())/1e9:.3f}bn across 5 funds."},
    ]
    return key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--key-only", action="store_true", help="rewrite answer_key.json without regenerating the documents")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.key_only:
        (out / "answer_key.json").write_text(json.dumps(answer_key(), indent=2))
        print("wrote answer_key.json")
        return 0
    northwind_factsheet(out, 9, "Northwind_GlobalMacro_Factsheet_Sep2026.pdf")
    northwind_factsheet(out, 8, "Northwind_GlobalMacro_Factsheet_Aug2026.pdf")
    northwind_csv(out)
    harbor_letter(out)
    harbor_quarterly(out)
    harbor_email(out)
    sable_factsheet(out)
    sable_csv(out)
    meridian_scanned(out)
    cobalt_statement(out)
    northwind_docx(out)
    meridian_xlsx(out)
    distractor(out)
    (out / "answer_key.json").write_text(json.dumps(answer_key(), indent=2))
    print(f"wrote {len(list(out.iterdir()))} files to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
