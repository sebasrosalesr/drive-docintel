import { useEffect, useRef, useState } from "react";
import { useReveal } from "../lib/gsap";
import type { Mode } from "../lib/labels";
import { get, post, Me } from "../api";

export default function Connect({ me, refresh, mode }: { me: Me | null; refresh: () => void; mode: Mode }) {
  const it = mode === "it";
  const [q, setQ] = useState("");
  const [folders, setFolders] = useState<any[]>([]);
  const [ref, setRef] = useState("");
  const [msg, setMsg] = useState("");
  const [sync, setSync] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { const t = () => get("/api/stats").then(setStats).catch(() => {}); t(); const id = setInterval(t, 10000); return () => clearInterval(id); }, []);
  const rereadAll = async (scope: "outdated" | "all") => {
    if (!confirm(scope === "all" ? "Read every document again with the latest reader? This calls the model for each one." : `Read the ${stats?.outdated_documents ?? 0} document(s) that were read with an older reader?`)) return;
    setBusy(true); try { const r = await post(`/api/documents/rerun-all?scope=${scope}`); setMsg(`${r.queued} document(s) queued for re-reading${r.skipped_no_original ? `; ${r.skipped_no_original} skipped (no original kept)` : ""}.`); } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  };
  const signed = !!me?.signed_in;

  useEffect(() => { if (!signed) return; const t = setTimeout(() => get(`/api/drive/folders?q=${encodeURIComponent(q)}`).then((r) => setFolders(r.folders)).catch((e) => setMsg(String(e))), 300); return () => clearTimeout(t); }, [q, signed]);
  useEffect(() => { const tick = () => get("/api/sync/status").then(setSync).catch(() => {}); tick(); const id = setInterval(tick, 5000); return () => clearInterval(id); }, []);

  const watch = async (r: string) => { setBusy(true); setMsg(""); try { const f = await post("/api/folders", { ref: r }); setMsg(`Watching “${f.name}”. First sync started.`); refresh(); } catch (e) { setMsg(String(e)); } finally { setBusy(false); } };
  const syncNow = async () => { setBusy(true); try { const r = await post("/api/sync"); setMsg("Sync: " + JSON.stringify(r.results)); refresh(); } catch (e) { setMsg(String(e)); } finally { setBusy(false); } };

  const pageRef = useRef<HTMLDivElement>(null);
  useReveal(pageRef, ".eyebrow, h1, .lede, .tablet");
  return (
    <div className="page" ref={pageRef}>
      <div className="eyebrow">Step 1</div>
      <h1>Connect Google Drive</h1>
      <p className="lede">{it ? "Sign in with Google, point the app at one folder, and every PDF, HTML email, CSV, Excel, Word, Google Doc or Sheet in it (and its subfolders) is read by the model into one table. New files are picked up on the next sync tick." : "Sign in with Google and choose the folder where your fund documents live. Anything you drop in there (PDFs, emails, spreadsheets, Word files) is read automatically within a minute."}</p>
      <div className="grid c2">
        <div className="tablet" data-tour="connect-google">
          <h3>Google account</h3>
          {!me?.google_ready ? (
            <div className="notice">{it ? <>Google OAuth is not configured on this server (<code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code>). You can still ingest a local folder: <code>python scripts/run_local.py corpus</code>.</> : "Google Drive is not connected on this server yet. Ask IT to add the Google sign-in keys; documents loaded another way still show up under Documents."}</div>
          ) : !signed ? (
            <a className="btn gold" href="/api/auth/google/start">Connect Google Drive</a>
          ) : (
            <div className="row"><span>Signed in as <b>{me?.email}</b></span>{me?.reauth_required && <span className="chip failed">access expired</span>}{me?.reauth_required && <a className="btn sm" href="/api/auth/google/start">Reconnect</a>}</div>
          )}
          {signed && (<>
            <h3>Pick the folder to watch</h3>
            <input placeholder="Search your folders…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", marginBottom: 8 }} />
            <div className="folders">{folders.length === 0 ? <div className="muted">No folders found.</div> : folders.map((f) => <div key={f.id} onClick={() => watch(f.id)}><span>{f.name}</span><span className="small muted">{(f.modifiedTime || "").slice(0, 10)}</span></div>)}</div>
            <div className="row" style={{ marginTop: 10 }}>
              <input placeholder="…or paste a folder URL / id" value={ref} onChange={(e) => setRef(e.target.value)} style={{ flex: 1 }} />
              <button className="btn" disabled={!ref || busy} onClick={() => watch(ref)}>Watch</button>
            </div>
          </>)}
          {msg && <div className="notice" style={{ marginTop: 10 }}>{msg}</div>}
        </div>
        <div className="tablet">
          {me?.watch_dir && (<div data-tour="connect-folder">
            <h3>Folder on this computer</h3>
            <div className="kv">
              <span className="k">Watching</span><span><b>{me.watch_dir.split("/").pop()}</b> <span className="mono muted small">{me.watch_dir}</span></span>
              <span className="k">Last scan</span><span>{sync?.local?.last_scan_at ? sync.local.last_scan_at.replace("T", " ") + " UTC" : "—"}</span>
              <span className="k">Last result</span><span className="mono small">{sync?.local?.last_summary ? `${sync.local.last_summary.listed} files · ${sync.local.last_summary.new} new · ${sync.local.last_summary.changed} changed · ${sync.local.last_summary.removed} removed` : "—"}</span>
            </div>
            <div className="row" style={{ marginTop: 10 }}><button className="btn" onClick={syncNow} disabled={busy}>Sync now</button><span className="small muted">Drop files into that folder; they are picked up within {sync?.interval_seconds ?? 60}s.</span></div>
            {sync?.local?.error && <div className="notice err" style={{ marginTop: 10 }}>{sync.local.error}</div>}
          </div>)}
          <h3>{me?.watch_dir ? "Google Drive sync" : "Sync"}</h3>
          {me?.folder ? (<>
            <div className="kv">
              <span className="k">Watching</span><span><b>{me.folder.name}</b> <span className="mono muted">{me.folder.folder_id}</span></span>
              <span className="k">Last tick</span><span>{me.folder.last_tick_at ? me.folder.last_tick_at.replace("T", " ") + " UTC" : "—"}</span>
              <span className="k">Last result</span><span className="mono small">{me.folder.last_tick_summary ? `${me.folder.last_tick_summary.listed} listed · ${me.folder.last_tick_summary.new} new · ${me.folder.last_tick_summary.changed} changed · ${me.folder.last_tick_summary.removed} removed` : "—"}</span>
              <span className="k">Interval</span><span>every {sync?.interval_seconds ?? 60}s{sync?.thread_alive ? "" : " (loop not running)"}</span>
              <span className="k">Files</span><span className="small">{sync?.counts ? Object.entries(sync.counts).map(([k, v]) => `${k} ${v}`).join(" · ") : "—"}</span>
            </div>
            <div className="row" style={{ marginTop: 12 }}><button className="btn" onClick={syncNow} disabled={busy}>Sync now</button>{sync?.running && <span className="chip extracting">tick running</span>}{sync?.inflight > 0 && <span className="chip extracting">{sync.inflight} extracting</span>}</div>
            {sync?.last_error && <div className="notice err" style={{ marginTop: 10 }}>{sync.last_error}</div>}
          </>) : <div className="muted">No folder watched yet.</div>}
          <div data-tour="connect-reading">
          <h3>Reading</h3>
          {stats && (<div className="kv small">
            <span className="k">Spent today</span><span>${Number(stats.today_cost_usd).toFixed(2)}{stats.daily_cost_cap_usd ? ` of a $${Number(stats.daily_cost_cap_usd).toFixed(2)} daily cap` : " (no daily cap set)"}</span>
            <span className="k">Reader version</span><span>{stats.prompt_version}{stats.outdated_documents ? ` · ${stats.outdated_documents} document${stats.outdated_documents === 1 ? "" : "s"} read with an older version` : " · everything is up to date"}</span>
          </div>)}
          <div className="row" style={{ marginTop: 8 }}>
            {stats?.outdated_documents > 0 && <button className="btn sm" onClick={() => rereadAll("outdated")} disabled={busy}>Re-read the {stats.outdated_documents} outdated</button>}
            <button className="btn ghost sm" onClick={() => rereadAll("all")} disabled={busy}>Re-read everything</button>
          </div>
          </div>
          {it && <h3>Model</h3>}
          {!it ? null : me?.llm_ready ? <div className="kv small"><span className="k">Extraction (A)</span><code>{me.model}</code><span className="k">Model B</span><code>{me.model_b || "—"}</code><span className="k">Ask</span><code>{me.ask_model}</code></div> : <span className="chip failed">OPENROUTER_API_KEY not set</span>}
        </div>
      </div>
    </div>
  );
}
