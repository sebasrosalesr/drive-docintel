import React, { useCallback, useEffect, useState } from "react";
import { get, post, Me } from "./api";
import type { Mode } from "./lib/labels";
import Ask from "./pages/Ask";
import Connect from "./pages/Connect";
import Data from "./pages/Data";
import Documents from "./pages/Documents";
import Tour, { tourDone } from "./components/Tour";

const PAGES = [["connect", "Connect"], ["documents", "Documents"], ["data", "Data"], ["ask", "Ask"]] as const;

export default function App() {
  const [page, setPage] = useState(() => (location.hash.replace("#", "") || "connect"));
  const [me, setMe] = useState<Me | null>(null);
  const [openDoc, setOpenDoc] = useState<{ id: number; page?: number } | null>(null);
  const [tour, setTour] = useState(false);
  useEffect(() => { if (me && (!me.auth_required || me.authed) && !tourDone()) { const t = setTimeout(() => setTour(true), 600); return () => clearTimeout(t); } }, [me?.authed, me?.auth_required]);
  // The IT view is parked for now: reachable with ?view=it, otherwise everyone gets the Team view.
  const mode: Mode = new URLSearchParams(location.search).get("view") === "it" ? "it" : "team";
  const refresh = useCallback(() => { get<Me>("/api/me").then(setMe).catch(() => {}); }, []);
  useEffect(() => { refresh(); const id = setInterval(refresh, 10000); const onHash = () => setPage(location.hash.replace("#", "") || "connect"); window.addEventListener("hashchange", onHash); return () => { clearInterval(id); window.removeEventListener("hashchange", onHash); }; }, [refresh]);
  useEffect(() => { if (!me) return; if (!location.hash && (me.folder || !me.google_ready)) location.hash = "documents"; }, [me?.folder?.id, me?.google_ready]);
  if (me && me.auth_required && !me.authed) return <Login onDone={refresh} />;
  return (<>
    <header className="topbar">
      <div className="wordmark">DRIVE <b>DOCINTEL</b></div>
      <nav className="nav">{PAGES.map(([k, l]) => <a key={k} href={`#${k}`} className={page === k ? "active" : ""}>{l}</a>)}</nav>
      <div className="pills">
        <button className="btn ghost sm tour-btn" onClick={() => setTour(true)}>Tutorial</button>
        {mode === "it" && <span className="pill"><span className={`dot ${me?.llm_ready ? "on" : "off"}`} />model</span>}
        <span className="pill"><span className={`dot ${me?.signed_in ? (me.reauth_required ? "warn" : "on") : me?.google_ready ? "warn" : "off"}`} />{me?.signed_in ? me.email : "Google"}</span>
        <span className="pill"><span className={`dot ${me?.folder || me?.watch_dir ? "on" : "off"}`} />{me?.folder ? me.folder.name : me?.watch_dir ? me.watch_dir.split("/").pop() : "no folder"}</span>
      </div>
    </header>
    {page === "connect" && <Connect me={me} refresh={refresh} mode={mode} />}
    {page === "documents" && <Documents openDoc={openDoc} setOpenDoc={setOpenDoc} mode={mode} />}
    {page === "data" && <Data openDoc={openDoc} setOpenDoc={setOpenDoc} mode={mode} />}
    {page === "ask" && <Ask openDoc={openDoc} setOpenDoc={setOpenDoc} llmReady={!!me?.llm_ready} mode={mode} />}
    <Tour open={tour} onClose={() => setTour(false)} />
  </>);
}


function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await post("/api/login", { password: pw }); onDone(); } catch (x) { setErr("That password is not right."); }
  };
  return (
    <div className="login">
      <form className="tablet" onSubmit={submit}>
        <div className="wordmark" style={{ color: "var(--forest)" }}>DRIVE <b style={{ color: "var(--forest-2)" }}>DOCINTEL</b></div>
        <h2 style={{ marginTop: 10 }}>Sign in</h2>
        <p className="muted small">This demo is protected with a password.</p>
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoFocus style={{ width: "100%", marginBottom: 10 }} />
        {err && <div className="notice err" style={{ marginBottom: 10 }}>{err}</div>}
        <button className="btn gold" type="submit" style={{ width: "100%" }}>Enter</button>
      </form>
    </div>
  );
}
