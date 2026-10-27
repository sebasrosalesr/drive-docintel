import { useMemo, useState } from "react";

export type Column<T> = { key: string; label: string; render?: (row: T) => React.ReactNode; num?: boolean; sort?: (row: T) => string | number | null | undefined; width?: string };

export default function DataTable<T extends Record<string, any>>({ rows, columns, onRow, empty = "Nothing here yet." }: { rows: T[]; columns: Column<T>[]; onRow?: (row: T) => void; empty?: string }) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const val = (r: T) => (col?.sort ? col.sort(r) : r[sort.key]);
    return [...rows].sort((a, b) => { const x = val(a), y = val(b); if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : x > y ? 1 : 0) * sort.dir; });
  }, [rows, sort, columns]);
  if (!rows.length) return <div className="empty">{empty}</div>;
  return (
    <table className="dt">
      <thead><tr>{columns.map((c) => (
        <th key={c.key} className={c.num ? "num" : ""} style={{ width: c.width }} onClick={() => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }))}>
          {c.label}{sort?.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
        </th>))}</tr></thead>
      <tbody>{sorted.map((r, i) => (
        <tr key={(r as any).key ?? (r as any).id ?? i} className={onRow ? "click" : ""} onClick={onRow ? () => onRow(r) : undefined}>
          {columns.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : String(r[c.key] ?? "")}</td>)}
        </tr>))}</tbody>
    </table>
  );
}
