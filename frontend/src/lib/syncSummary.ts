/** The sync's own report, said in words. The endpoint returns one summary per
 * watched folder: {listed, new, changed, unchanged, removed, pending, at}. */
export type SyncSummary = { listed?: number; new?: number; changed?: number; unchanged?: number; removed?: number; pending?: number; at?: string };

const n = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const plural = (count: number, one: string, many = one + "s") => `${count} ${count === 1 ? one : many}`;

export function describeSync(results: unknown): string {
  const list = (Array.isArray(results) ? results : results ? [results] : []).filter((r): r is SyncSummary => !!r && typeof r === "object");
  if (!list.length) return "Synced. Nothing to report.";
  const total = (key: keyof SyncSummary) => list.reduce((acc, r) => acc + n(r[key]), 0);
  const listed = total("listed"), fresh = total("new"), changed = total("changed"), removed = total("removed"), pending = total("pending");
  const changes = [fresh && plural(fresh, "new file"), changed && plural(changed, "changed file"), removed && plural(removed, "file removed")].filter(Boolean) as string[];
  const head = `Synced just now: ${plural(listed, "file")} in the folder`;
  const whatChanged = changes.length ? changes.join(", ") : "nothing new";
  const queue = pending ? `${plural(pending, "file")} waiting to be read` : "everything read";
  return `${head}, ${whatChanged}, ${queue}.`;
}

/** The folder card's "last result" line: counts only, dot-separated. */
export function summarizeTick(s: SyncSummary | null | undefined): string {
  if (!s) return "—";
  const parts = [`${n(s.listed)} listed`, `${n(s.new)} new`, `${n(s.changed)} changed`, `${n(s.removed)} removed`];
  if (n(s.pending)) parts.push(`${n(s.pending)} waiting`);
  return parts.join(" · ");
}
