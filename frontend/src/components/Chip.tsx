export default function Chip({ v, label }: { v: string; label?: string }) {
  const cls = ["done", "needs_review", "failed", "rejected", "pending", "extracting", "skipped", "removed", "high", "medium", "low", "gold"].includes(v) ? v : "other";
  return <span className={`chip ${cls}`}>{label ?? v.replace("_", " ")}</span>;
}
