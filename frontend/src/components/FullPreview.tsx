import { useEffect } from "react";
import Preview, { PreviewData } from "./Preview";

/** The original, filling the window: a bar with the name, "open in a new tab"
 * when there is a URL to open, and Close; Escape closes too, and the key
 * stops here so the drawer behind stays open. */
export default function FullPreview({ title, data, page, onClose }: { title: string; data: PreviewData | null; page?: number; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey, true); document.body.style.overflow = prev; };
  }, [onClose]);
  const url = data && (data.kind === "pdf" || data.kind === "html") ? data.url : null;
  return (
    <div className="preview-full" role="dialog" aria-modal="true" aria-label={`${title}, full window`}>
      <div className="preview-full-bar">
        <span className="preview-full-title" title={title}>{title}</span>
        <span style={{ flex: 1 }} />
        {url && <a className="btn ghost sm" href={url + (page ? `#page=${page}` : "")} target="_blank" rel="noopener noreferrer">Open in a new tab</a>}
        <button className="btn sm" onClick={onClose} aria-label="Close the full window">Close <kbd>Esc</kbd></button>
      </div>
      <div className="preview-full-body"><Preview data={data} page={page} /></div>
    </div>
  );
}
