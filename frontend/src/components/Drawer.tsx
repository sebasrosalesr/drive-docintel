import { useEffect } from "react";

export default function Drawer({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (<>
    <div className="drawer-backdrop" onClick={onClose} />
    <aside className="drawer" role="dialog" aria-modal="true">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      {children}
    </aside>
  </>);
}
