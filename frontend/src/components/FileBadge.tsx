export type FileInfo = { kind: string; label: string; ext: string };
const COLORS: Record<string, string> = { pdf: "#8c001a", xlsx: "#194e3b", csv: "#a3781a", docx: "#1f4e9a", html: "#5a4634", eml: "#4a5568", text: "#6d7078", pptx: "#b4532a", image: "#3f5f7a" };

export default function FileBadge({ file, showLabel = true }: { file?: FileInfo; showLabel?: boolean }) {
  if (!file) return null;
  const c = COLORS[file.kind] ?? "#6d7078";
  return (
    <span className="file-badge" title={`${file.label} (.${file.ext})`}>
      <span className="file-ext" style={{ background: c }}>{file.ext.toUpperCase() || "FILE"}</span>
      {showLabel && <span className="file-label">{file.label}</span>}
    </span>
  );
}
