// Plain-language labels for the Team view; the IT view shows the raw codes.
export type Mode = "team" | "it";

export const STATUS_PLAIN: Record<string, string> = {
  pending: "Waiting", extracting: "Reading…", done: "Ready", needs_review: "Needs a look", failed: "Couldn't read",
  skipped: "Not supported", removed: "Removed from folder", rejected: "Not allowed (personal ID)",
};
export const DOC_TYPE_PLAIN: Record<string, string> = {
  factsheet: "Fund factsheet", statement: "Account statement", performance_report: "Performance report", email_update: "Email update",
  portfolio_analysis: "Portfolio analysis", offering: "Offering / pipeline", term_sheet: "Rates & terms", brochure: "Brochure",
  letter: "Letter", presentation: "Presentation", agreement: "Agreement", invoice: "Invoice", other: "Other document", identity_document: "Personal ID document",
};
export const FLAG_PLAIN: Record<string, string> = {
  missing_manager: "No manager name was found", missing_as_of: "No as-of date was found", not_financial: "Doesn't look like a financial document",
  no_metrics: "No usable figures were found (it may be a sample or use placeholder values)", out_of_range: "A figure looks out of range", compounding_mismatch: "The monthly returns don't add up to the stated yearly return",
  evidence_unverified: "Some figures couldn't be matched to the document text", maybe_fraction: "A return may be a fraction rather than a percentage",
  drawdown_sign: "A drawdown is shown as a positive number", no_summary: "We could not summarise this document",
  identity_document: "This looks like a personal ID document, so it was not read", pii_redacted: "Personal identifiers (SSN, card or account numbers) were masked before reading",
};
export const METRIC_PLAIN: Record<string, string> = {
  return: "Return", benchmark_return: "Benchmark return", aum: "Assets (AUM)", nav: "NAV", expense_ratio: "Expense ratio",
  mgmt_fee: "Management fee", perf_fee: "Performance fee", sharpe: "Sharpe ratio", volatility: "Volatility", max_drawdown: "Max drawdown", other: "Other",
};
export const PERIOD_PLAIN: Record<string, string> = {
  month: "Month", quarter: "Quarter", ytd: "Year to date", year: "Calendar year", "1y": "1 year", "3y": "3 years", "5y": "5 years",
  since_inception: "Since inception", point: "As of a date", other: "Other",
};

export const statusLabel = (s: string, mode: Mode) => (mode === "it" ? s.replace("_", " ") : STATUS_PLAIN[s] ?? s);
export const docTypeLabel = (t: string | undefined, mode: Mode) => (!t ? "" : mode === "it" ? t : DOC_TYPE_PLAIN[t] ?? t);
export const flagText = (f: { code: string; msg: string }, mode: Mode) => (mode === "it" ? `${f.code}: ${f.msg}` : FLAG_PLAIN[f.code] ?? f.msg);
export const metricLabel = (m: string, mode: Mode) => (mode === "it" ? m : METRIC_PLAIN[m] ?? m);
export const periodLabel = (p: string, mode: Mode) => (mode === "it" ? p : PERIOD_PLAIN[p] ?? p);
export const baseName = (name: string) => name.replace(/\.[A-Za-z0-9]{1,5}$/, "");
