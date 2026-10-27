// Tiny Markdown renderer: headings, bullets, bold, inline code, pipe tables, and [doc:N]/[obs:N] citation chips.
import React from "react";

export type CiteFn = (kind: string, id: number, page?: number) => void;
export type CiteLabels = Record<number, string>;

function inline(text: string, onCite?: CiteFn, labels?: CiteLabels): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[doc:\d+(?:\s*pp?\.?\s*[\d,\-–\s p.]+?)?\s*\]|\[(?:obs|fact):\d+\]|\[unverified\])/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<b key={k++}>{t.slice(2, -2)}</b>);
    else if (t.startsWith("`")) out.push(<code key={k++}>{t.slice(1, -1)}</code>);
    else if (t === "[unverified]") out.push(<span key={k++} className="cite bad" title="This citation did not match anything the model read">unverified</span>);
    else if (t.startsWith("[doc:")) {
      const mm = /\[doc:(\d+)(?:\s*pp?\.?\s*([\d,\-–\s p.]+?))?\s*\]/.exec(t)!;
      const id = Number(mm[1]);
      const pageText = mm[2] ? mm[2].replace(/p\./g, "").replace(/\s+/g, "").replace(/,/g, ", ") : "";
      const page = mm[2] ? Number((mm[2].match(/\d+/) || [""])[0]) || undefined : undefined;
      const title = labels?.[id];
      out.push(<span key={k++} className="cite doc" title={title ? `${title}${pageText ? `, page ${pageText}` : ""}` : `document ${id}`} onClick={() => onCite?.("doc", id, page)}>{title ? title.slice(0, 28) + (title.length > 28 ? "…" : "") : `doc ${id}`}{pageText ? <span className="pg"> p.{pageText}</span> : null}</span>);
    } else { const [kind, id] = t.slice(1, -1).split(":"); out.push(<span key={k++} className="cite" title={kind === "obs" ? "a figure read from a document" : "a fact read from a document"} onClick={() => onCite?.(kind, Number(id))}>{kind === "obs" ? "figure" : "fact"}</span>); }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text, onCite, labels, caret = false }: { text: string; onCite?: CiteFn; labels?: CiteLabels; caret?: boolean }) {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) { const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim()); if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells); i++; }
      if (rows.length) blocks.push(<table key={k++}><thead><tr>{rows[0].map((c, j) => <th key={j}>{inline(c, onCite, labels)}</th>)}</tr></thead><tbody>{rows.slice(1).map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, onCite, labels)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    if (/^\s*[-*] /.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*] /.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*] /, "")); i++; }
      blocks.push(<ul key={k++}>{items.map((it, j) => <li key={j}>{inline(it, onCite, labels)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)] /.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)] /.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+[.)] /, "")); i++; }
      blocks.push(<ol key={k++}>{items.map((it, j) => <li key={j}>{inline(it, onCite, labels)}</li>)}</ol>);
      continue;
    }
    if (/^#{1,3} /.test(l)) { blocks.push(<h3 key={k++} style={{ margin: "10px 0 4px" }}>{inline(l.replace(/^#+ /, ""), onCite, labels)}</h3>); i++; continue; }
    if (l.trim() === "") { i++; continue; }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !lines[i].trim().startsWith("|") && !/^\s*[-*] /.test(lines[i]) && !/^\s*\d+[.)] /.test(lines[i]) && !/^#{1,3} /.test(lines[i])) { para.push(lines[i]); i++; }
    blocks.push(<p key={k++} style={{ margin: "6px 0" }}>{inline(para.join(" "), onCite, labels)}</p>);
  }
  if (caret) {
    const last = blocks[blocks.length - 1] as React.ReactElement | undefined;
    if (last && last.type === "p") blocks[blocks.length - 1] = <p key={last.key ?? "last"} style={{ margin: "6px 0" }}>{(last.props as any).children}<span className="caret" /></p>;
    else blocks.push(<p key="caret" style={{ margin: "6px 0" }}><span className="caret" /></p>);
  }
  return <div className="answer">{blocks}</div>;
}
