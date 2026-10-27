export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw new Error(await errText(r));
  return r.json();
}
/** POST and read an NDJSON stream; onEvent gets each parsed line as it arrives. */
export async function streamPost(path: string, body: unknown, onEvent: (ev: any) => void, signal?: AbortSignal): Promise<void> {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) throw new Error(await errText(r));
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) { try { onEvent(JSON.parse(line)); } catch { /* partial line */ } }
    }
  }
  if (buf.trim()) { try { onEvent(JSON.parse(buf)); } catch { /* ignore */ } }
}

async function errText(r: Response) {
  try { const j = await r.json(); return j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : JSON.stringify(j); } catch { return `${r.status} ${r.statusText}`; }
}

export type Me = { auth_required: boolean; authed: boolean; signed_in: boolean; google_ready: boolean; llm_ready: boolean; model: string; model_b: string; ask_model: string; watch_dir: string | null; email: string; name: string; reauth_required: boolean;
  folder: null | { id: number; folder_id: string; name: string; last_tick_at: string | null; last_tick_summary: any } };
export type DocSummary = { document_id: number; doc_type: string; manager: string; as_of_date: string | null; currency: string; status: string; error: string; n_rows: number;
  flags: { code: string; msg: string }[]; warnings: string[]; cost_usd: number; duration_ms: number; is_scanned: boolean; page_count: number; ocr_pages: number; title: string; summary: string; key_points: string[]; n_facts: number; model: string; engine: string; created_at: string };
export type Item = { key: string; source: string; file_id: number | null; name: string; mime: string; status: string; error: string; attempts: number; modified_time: string; size: number; document: DocSummary | null };
export type Obs = { id: number; fund: string; fund_id: number; share_class: string; metric: string; metric_label: string; period_type: string; period_label: string; period_year: number | null;
  period_month: number | null; period_start: string | null; period_end: string | null; value: number; unit: string; annualized: boolean; basis: string; currency: string;
  evidence_text: string; evidence_verified: boolean; evidence_note: string; page: number; confidence: string };

export function fmtValue(v: number, unit: string, currency = "", metric = "") {
  if (unit === "pct") return `${v > 0 && (metric === "return" || metric === "benchmark_return") ? "+" : ""}${v.toFixed(2)}%`;
  if (unit === "currency") return `${currency ? currency + " " : ""}${v >= 1e9 ? (v / 1e9).toFixed(2) + "bn" : v >= 1e6 ? (v / 1e6).toFixed(1) + "m" : v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (unit === "multiple") return `${v.toFixed(2)}x`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
export const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
