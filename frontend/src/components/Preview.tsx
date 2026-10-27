import { useState } from "react";

type Grid = { kind: "grid"; sheets: { name: string; rows: string[][] }[] };
type Docx = { kind: "docx"; blocks: ({ type: "p"; text: string; style: string } | { type: "table"; rows: string[][] })[] };
type Email = { kind: "email"; headers: Record<string, string>; html: string | null; text: string; attachments: string[] };
export type PreviewData = { kind: "pdf" | "html"; url: string } | Grid | Docx | Email | { kind: "text"; text: string; note?: string };

const col = (i: number) => { let s = ""; i++; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; };

export default function Preview({ data, page }: { data: PreviewData | null; page?: number }) {
  const [sheet, setSheet] = useState(0);
  if (!data) return <div className="empty">Loading the original…</div>;
  if (data.kind === "pdf") return <iframe className="preview-frame" src={data.url + (page ? `#page=${page}` : "")} title="Original PDF" />;
  if (data.kind === "html") return <iframe className="preview-frame" src={data.url} title="Original page" sandbox="" />;
  if (data.kind === "grid") {
    const s = data.sheets[Math.min(sheet, data.sheets.length - 1)];
    const width = Math.max(1, ...s.rows.map((r) => r.length));
    return (
      <div className="sheet">
        {data.sheets.length > 1 && <div className="sheet-tabs">{data.sheets.map((sh, i) => <button key={sh.name} className={i === sheet ? "active" : ""} onClick={() => setSheet(i)}>{sh.name}</button>)}</div>}
        <div className="sheet-scroll">
          <table className="xl">
            <thead><tr><th className="rn"></th>{Array.from({ length: width }, (_, i) => <th key={i}>{col(i)}</th>)}</tr></thead>
            <tbody>{s.rows.map((r, ri) => <tr key={ri}><td className="rn">{ri + 1}</td>{Array.from({ length: width }, (_, ci) => <td key={ci} className={/^-?\(?\d[\d,.]*\)?%?$/.test(r[ci] ?? "") ? "num" : ""}>{r[ci] ?? ""}</td>)}</tr>)}</tbody>
          </table>
        </div>
        {data.sheets.length > 1 && <div className="small muted" style={{ marginTop: 6 }}>Sheet {sheet + 1} of {data.sheets.length}</div>}
      </div>
    );
  }
  if (data.kind === "docx") {
    return (
      <div className="docx-page">
        {data.blocks.map((b, i) => b.type === "table"
          ? <table className="docx-table" key={i}><tbody>{b.rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => ri === 0 ? <th key={ci}>{c}</th> : <td key={ci}>{c}</td>)}</tr>)}</tbody></table>
          : /heading 1|title/i.test(b.style) ? <h2 key={i}>{b.text}</h2> : /heading/i.test(b.style) ? <h3 key={i}>{b.text}</h3> : <p key={i}>{b.text}</p>)}
      </div>
    );
  }
  if (data.kind === "email") {
    return (
      <div className="email-card">
        <div className="email-head">
          {(["From", "To", "Date", "Subject"] as const).map((k) => data.headers[k] ? <div key={k}><span className="k">{k}</span><span>{data.headers[k]}</span></div> : null)}
          {data.attachments.length > 0 && <div><span className="k">Attachments</span><span>{data.attachments.join(", ")}</span></div>}
        </div>
        {data.html ? <iframe className="preview-frame email-body" srcDoc={data.html} title="Email body" sandbox="" /> : <pre style={{ whiteSpace: "pre-wrap" }}>{data.text}</pre>}
      </div>
    );
  }
  if (data.kind === "text") return <>{data.note && <div className="notice">{data.note}</div>}<pre style={{ whiteSpace: "pre-wrap", maxHeight: "60vh" }}>{data.text}</pre></>;
  return null;
}
