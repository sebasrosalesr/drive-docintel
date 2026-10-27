import { useCallback, useEffect, useRef, useState } from "react";
import { get, Item } from "../api";
import Chip from "../components/Chip";
import DataTable, { Column } from "../components/DataTable";
import DocumentDrawer from "../components/DocumentDrawer";
import FileBadge from "../components/FileBadge";
import { useReveal } from "../lib/gsap";
import { baseName, docTypeLabel, flagText, Mode, statusLabel } from "../lib/labels";

export default function Documents({ openDoc, setOpenDoc, mode }: { openDoc: { id: number; page?: number } | null; setOpenDoc: (d: { id: number; page?: number } | null) => void; mode: Mode }) {
  const [items, setItems] = useState<Item[]>([]);
  const [filter, setFilter] = useState("");
  const pageRef = useRef<HTMLDivElement>(null);
  useReveal(pageRef, ".eyebrow, h1, .lede, .filters, .tablet");
  useEffect(() => { const load = () => get("/api/documents").then((r) => setItems(r.items)).catch(() => {}); load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, []);
  useEffect(() => {
    const openFirst = () => { const first = items.find((i) => i.document && i.status !== "rejected"); if (first?.document) setOpenDoc({ id: first.document.document_id }); };
    const close = () => setOpenDoc(null);
    window.addEventListener("docintel:open-first-doc", openFirst); window.addEventListener("docintel:close-drawer", close);
    return () => { window.removeEventListener("docintel:open-first-doc", openFirst); window.removeEventListener("docintel:close-drawer", close); };
  }, [items, setOpenDoc]);
  const it = mode === "it";
  const rows = items.filter((i) => !filter || i.status === filter);
  const team: Column<Item>[] = [
    { key: "name", label: "Document", render: (r) => <div className="row" style={{ gap: 10, flexWrap: "nowrap" }}><FileBadge file={(r as any).file} showLabel={false} /><div><div>{r.document?.title || baseName(r.name)}</div><div className="small muted">{r.document?.title ? baseName(r.name) + " · " : ""}{(r as any).file?.label}{r.source === "drive" ? " · from Drive" : r.source === "folder" ? " · from the watched folder" : r.source === "upload" ? " · uploaded" : r.source === "attachment" ? " · email attachment" : r.source === "sample" ? " · sample library" : ""}</div></div></div> },
    { key: "doc_type", label: "Type", render: (r) => docTypeLabel(r.document?.doc_type, mode), sort: (r) => r.document?.doc_type },
    { key: "manager", label: "From", render: (r) => r.document?.manager ?? "", sort: (r) => r.document?.manager },
    { key: "as_of", label: "As of", render: (r) => r.document?.as_of_date ?? "", sort: (r) => r.document?.as_of_date },
    { key: "rows", label: "Figures · facts", num: true, render: (r) => r.document ? `${r.document.n_rows} · ${r.document.n_facts ?? 0}` : "", sort: (r) => r.document?.n_rows },
    { key: "status", label: "Status", render: (r) => <><Chip v={r.status} label={statusLabel(r.status, mode)} />{r.document && r.document.flags.length > 0 ? <div className="small muted">{r.document.flags.map((f) => flagText(f, mode)).join(" · ")}</div> : null}{r.status === "failed" && r.error ? <div className="small muted">We couldn't read this file.</div> : null}{r.status === "rejected" ? <div className="small muted">Looks like a personal ID document. Not sent to the model, nothing kept.</div> : null}</> },
  ];
  const itCols: Column<Item>[] = [
    { key: "name", label: "File", render: (r) => <><div>{r.name}</div><div className="small muted">{r.source} · {r.mime || "—"} · {(r.modified_time || "").slice(0, 10)}</div></> },
    { key: "kind", label: "Kind", render: (r) => <FileBadge file={(r as any).file} />, sort: (r) => (r as any).file?.kind },
    { key: "doc_type", label: "doc_type", render: (r) => r.document?.doc_type ?? "", sort: (r) => r.document?.doc_type },
    { key: "manager", label: "Manager", render: (r) => r.document?.manager ?? "", sort: (r) => r.document?.manager },
    { key: "as_of", label: "As of", render: (r) => r.document?.as_of_date ?? "", sort: (r) => r.document?.as_of_date },
    { key: "rows", label: "Rows", num: true, render: (r) => r.document?.n_rows ?? "", sort: (r) => r.document?.n_rows },
    { key: "status", label: "Status", render: (r) => <><Chip v={r.status} />{r.document?.is_scanned && <> <Chip v="gold" label="scan" /></>}{r.status === "failed" && r.error ? <div className="small muted" title={r.error}>{r.error.slice(0, 70)}</div> : null}{r.document && r.document.flags.length > 0 ? <div className="small muted">{r.document.flags.map((f) => f.code).join(", ")}</div> : null}{r.attempts > 1 ? <div className="small muted">attempt {r.attempts}</div> : null}</> },
    { key: "model", label: "Model", render: (r) => r.document ? <span className="small">{r.document.model.split("/").pop()}<div className="muted">{r.document.engine} · {(r.document.duration_ms / 1000).toFixed(0)}s</div></span> : "", sort: (r) => r.document?.model },
    { key: "cost", label: "Cost", num: true, render: (r) => (r.document ? `$${r.document.cost_usd.toFixed(3)}` : ""), sort: (r) => r.document?.cost_usd },
  ];
  const counts = items.reduce((a, i) => ((a[i.status] = (a[i.status] || 0) + 1), a), {} as Record<string, number>);
  const [drag, setDrag] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f, f.name));
    setUploadMsg(`Uploading ${list.length} file${list.length === 1 ? "" : "s"}…`);
    try {
      const r = await fetch("/api/upload", { method: "POST", body: fd, credentials: "same-origin" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      setUploadMsg(`${j.accepted.length} file${j.accepted.length === 1 ? "" : "s"} being read now${j.rejected.length ? `; skipped ${j.rejected.map((x: any) => `${x.name} (${x.reason})`).join(", ")}` : ""}.`);
      get("/api/documents").then((res) => setItems(res.items)).catch(() => {});
    } catch (e) { setUploadMsg(String(e)); }
  }, []);
  return (
    <div className="page" ref={pageRef}>
      <div className="eyebrow">Step 2</div>
      <h1>Documents</h1>
      <p className="lede">{it ? "Every file the sync has seen, its pipeline status, model, cost and validation codes. Open a row for the extraction, the evidence checks, the extracted text and the raw JSON."
        : "Every document in the folder, what kind it is, who it is from, and whether it is ready. Open one to see the original file and the figures we read out of it, each next to the line it came from."}</p>
      <div className="filters">
        <button className={`btn sm ${filter ? "ghost" : ""}`} onClick={() => setFilter("")}>All {items.length}</button>
        {Object.entries(counts).map(([s, n]) => <button key={s} className={`btn sm ${filter === s ? "" : "ghost"}`} onClick={() => setFilter(s)}>{statusLabel(s, mode)} {n}</button>)}
      </div>
      <div className={`dropzone ${drag ? "over" : ""}`} data-tour="docs-dropzone"
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}>
        <input ref={fileRef} type="file" multiple hidden accept=".pdf,.csv,.xlsx,.xlsm,.docx,.html,.htm,.eml,.txt" onChange={(e) => { if (e.target.files) upload(e.target.files); e.target.value = ""; }} />
        <div><b>Add documents</b> <span className="muted">— drop PDFs, spreadsheets, Word files or emails here{it ? " (same pipeline as the Drive sync)" : ""}</span></div>
        <button className="btn sm ghost" type="button" onClick={() => fileRef.current?.click()}>Choose files</button>
        {uploadMsg && <div className="small" style={{ width: "100%", color: "var(--gold-text)" }}>{uploadMsg}</div>}
      </div>
      <div className="tablet" data-tour="docs-table"><DataTable rows={rows} columns={it ? itCols : team} onRow={(r) => r.document && setOpenDoc({ id: r.document.document_id })} empty={it ? "No documents yet. Watch a folder, or run scripts/run_local.py on a local folder." : "No documents yet. Connect a Drive folder to get started."} /></div>
      <DocumentDrawer docId={openDoc?.id ?? null} page={openDoc?.page} onClose={() => setOpenDoc(null)} mode={mode} />
    </div>
  );
}
