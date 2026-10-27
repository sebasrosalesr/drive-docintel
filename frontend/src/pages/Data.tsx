import { useEffect, useRef, useState } from "react";
import { useReveal } from "../lib/gsap";
import { metricLabel, Mode, periodLabel } from "../lib/labels";
import { fmtValue, get, post, MONTHS } from "../api";
import Chip from "../components/Chip";
import DataTable, { Column } from "../components/DataTable";
import DocumentDrawer from "../components/DocumentDrawer";

const METRICS = ["return", "benchmark_return", "aum", "nav", "expense_ratio", "mgmt_fee", "perf_fee", "sharpe", "volatility", "max_drawdown", "other"];
const PERIODS = ["month", "quarter", "ytd", "year", "1y", "3y", "5y", "since_inception", "point", "other"];

export default function Data({ openDoc, setOpenDoc, mode }: { openDoc: { id: number; page?: number } | null; setOpenDoc: (d: { id: number; page?: number } | null) => void; mode: Mode }) {
  const it = mode === "it";
  const [stats, setStats] = useState<any>(null);
  const [funds, setFunds] = useState<any[]>([]);
  const [f, setF] = useState<Record<string, string>>({ fund_id: "", manager: "", metric: "", period_type: "", year: "", month: "", basis: "", q: "" });
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [factQ, setFactQ] = useState("");
  const [dups, setDups] = useState<any[]>([]);
  const [mergeMsg, setMergeMsg] = useState("");
  const loadDups = () => get("/api/funds/duplicates").then((r) => setDups(r.pairs)).catch(() => {});
  useEffect(() => { loadDups(); }, [rows.length]);
  const merge = async (from: any, into: any) => {
    if (!confirm(`Treat “${from.name}” as the same fund as “${into.name}”? Its ${from.n} figure(s) move over and the name is kept as an alias.`)) return;
    try { const r = await post(`/api/funds/${from.id}/merge`, { into: into.id }); setMergeMsg(`Merged: ${r.moved_observations} figure(s) now under “${r.name}”.`); loadDups(); get("/api/funds").then((x) => setFunds(x.funds)); setF({ ...f }); } catch (e) { setMergeMsg(String(e)); }
  };
  const [facts, setFacts] = useState<any[]>([]);
  useEffect(() => { const t = setTimeout(() => get(`/api/facts?q=${encodeURIComponent(factQ)}`).then((r) => setFacts(r.rows)).catch(() => {}), 150); return () => clearTimeout(t); }, [factQ]);
  useEffect(() => { get("/api/stats").then(setStats); get("/api/funds").then((r) => setFunds(r.funds)); }, [rows.length]);
  useEffect(() => {
    const qs = Object.entries(f).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    const t = setTimeout(() => get(`/api/observations?${qs}`).then((r) => { setRows(r.rows); setTotal(r.total); }), 150);
    return () => clearTimeout(t);
  }, [f]);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const cols: Column<any>[] = [
    { key: "fund", label: "Fund", render: (r) => <>{r.fund}{r.share_class ? <div className="small muted">{r.share_class}</div> : null}</> },
    { key: "manager", label: "Manager" },
    { key: "metric", label: it ? "Metric" : "What", render: (r) => <>{metricLabel(r.metric, mode)}<div className="small muted">{r.metric_label}</div></> },
    { key: "period_label", label: "Period", render: (r) => <>{r.period_label}<div className="small muted">{periodLabel(r.period_type, mode)}{r.period_year ? ` · ${r.period_month ? MONTHS[r.period_month] + " " : ""}${r.period_year}` : ""}</div></>, sort: (r) => r.period_end },
    { key: "value", label: "Value", num: true, render: (r) => <>{fmtValue(r.value, r.unit, r.currency, r.metric)}{!it && r.basis !== "unknown" ? <div className="small muted">{r.basis}</div> : null}</> },
    ...(it ? [{ key: "basis", label: "Basis" } as Column<any>] : []),
    { key: "confidence", label: it ? "Conf." : "Checked", render: (r) => it ? <><Chip v={r.confidence} /> {r.evidence_verified ? <span className="badge-ok small">✓</span> : <span className="badge-no small">✗</span>}</> : (r.evidence_verified ? <span className="badge-ok">✓ matches</span> : <span className="badge-no small">{r.confidence === "high" ? "✓ read" : "needs a look"}</span>) },
    { key: "document_name", label: "Source", render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpenDoc({ id: r.document_id }); }}>{r.document_name}</a> },
  ];
  const pageRef = useRef<HTMLDivElement>(null);
  useReveal(pageRef, ".eyebrow, h1, .lede, .filters, .stat, .tablet");
  return (
    <div className="page" ref={pageRef}>
      <div className="eyebrow">Step 3</div>
      <h1>Extracted data</h1>
      <p className="lede">{it ? "One long table: every figure from every document, normalised to fund · metric · period. Filter it, sort it, export it." : "Every figure from every document in one place. Filter by fund, manager, what it measures or when, and export to Excel."}</p>
      {stats && <div className="grid c4" style={{ marginBottom: 16 }} data-tour="data-stats">
        <div className="tablet stat"><div className="v">{Object.values(stats.documents as Record<string, number>).reduce((a, b) => a + b, 0)}</div><div className="l">documents · {stats.documents.needs_review || 0} to review</div></div>
        <div className="tablet stat"><div className="v">{stats.observations}</div><div className="l">figures extracted</div></div>
        <div className="tablet stat"><div className="v">{stats.funds}</div><div className="l">funds · {stats.managers.length} managers</div></div>
        {it ? <div className="tablet stat"><div className="v">${Number(stats.cost_usd).toFixed(2)}</div><div className="l">model spend</div></div> : <div className="tablet stat"><div className="v">{stats.documents.done || 0}</div><div className="l">documents ready</div></div>}
      </div>}
      <div className="tablet" data-tour="data-filters">
        <div className="filters">
          <select value={f.fund_id} onChange={set("fund_id")}><option value="">All funds</option>{funds.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
          <select value={f.manager} onChange={set("manager")}><option value="">All managers</option>{(stats?.managers || []).map((m: string) => <option key={m} value={m}>{m}</option>)}</select>
          <select value={f.metric} onChange={set("metric")}><option value="">All metrics</option>{METRICS.map((m) => <option key={m} value={m}>{metricLabel(m, mode)}</option>)}</select>
          <select value={f.period_type} onChange={set("period_type")}><option value="">Any period</option>{PERIODS.map((m) => <option key={m} value={m}>{periodLabel(m, mode)}</option>)}</select>
          <select value={f.year} onChange={set("year")}><option value="">Any year</option>{[2024, 2025, 2026, 2027].map((y) => <option key={y} value={y}>{y}</option>)}</select>
          <select value={f.month} onChange={set("month")}><option value="">Any month</option>{MONTHS.slice(1).map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select>
          {it && <select value={f.basis} onChange={set("basis")}><option value="">Any basis</option><option>net</option><option>gross</option><option>unknown</option></select>}
          <input placeholder="Search…" value={f.q} onChange={set("q")} />
          <span style={{ flex: 1 }} />
          <span className="small muted" style={{ alignSelf: "center" }}>{total} rows</span>
          <a className="btn ghost sm" href="/api/observations.csv">{it ? "Export CSV" : "Export to Excel (CSV)"}</a>
        </div>
        <DataTable rows={rows} columns={cols} empty="No figures match." />
      </div>
      {dups.length > 0 && (
        <div className="tablet" style={{ marginTop: 16 }}>
          <h2 style={{ marginBottom: 4 }}>These look like the same fund</h2>
          <p className="lede" style={{ marginBottom: 8 }}>Different documents spell fund names differently. Merge the ones that are really the same so filters and answers line up.</p>
          {mergeMsg && <div className="notice" style={{ marginBottom: 8 }}>{mergeMsg}</div>}
          <table className="dt"><tbody>
            {dups.map((p, i) => (
              <tr key={i}>
                <td><b>{p.a.name}</b><div className="small muted">{p.a.manager} · {p.a.n} figure{p.a.n === 1 ? "" : "s"}</div></td>
                <td className="muted" style={{ textAlign: "center" }}>≈</td>
                <td><b>{p.b.name}</b><div className="small muted">{p.b.manager} · {p.b.n} figure{p.b.n === 1 ? "" : "s"}</div></td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="btn sm ghost" onClick={() => merge(p.b, p.a)}>Keep “{p.a.name.slice(0, 18)}{p.a.name.length > 18 ? "…" : ""}”</button>{" "}
                  <button className="btn sm ghost" onClick={() => merge(p.a, p.b)}>Keep “{p.b.name.slice(0, 18)}{p.b.name.length > 18 ? "…" : ""}”</button>
                </td>
              </tr>))}
          </tbody></table>
        </div>
      )}
      <div className="tablet" style={{ marginTop: 16 }} data-tour="data-facts">
        <div className="filters" style={{ alignItems: "center" }}>
          <h2 style={{ margin: 0, flex: 1 }}>Key facts</h2>
          <input placeholder="Search terms, minimums, rates, dates…" value={factQ} onChange={(e) => setFactQ(e.target.value)} style={{ minWidth: 280 }} />
          <span className="small muted">{facts.length} facts</span>
        </div>
        <p className="lede" style={{ marginTop: 0 }}>Everything with a value that is not a performance figure: minimums, target sizes, rates, fees in text, closing dates, terms.</p>
        <DataTable rows={facts.map((f) => ({ ...f, key: f.fact_id }))} empty="No key facts yet." columns={[
          { key: "subject", label: "About", render: (f: any) => f.subject || <span className="muted">the document</span> },
          { key: "attribute", label: it ? "Attribute" : "What" },
          { key: "value_text", label: "Value", render: (f: any) => <b>{f.value_text}</b> },
          { key: "manager", label: "From" },
          { key: "document_name", label: "Source", render: (f: any) => <a href="#" onClick={(e) => { e.preventDefault(); setOpenDoc({ id: f.document_id }); }}>{f.document_title || f.document_name}</a> },
        ]} />
      </div>
      <DocumentDrawer docId={openDoc?.id ?? null} page={openDoc?.page} onClose={() => setOpenDoc(null)} mode={mode} />
    </div>
  );
}
