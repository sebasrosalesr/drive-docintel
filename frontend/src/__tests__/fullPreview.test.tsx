import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FullPreview from "../components/FullPreview";

describe("FullPreview", () => {
  it("fills the window with the original, names it, and offers a new tab for a PDF", () => {
    const out = renderToStaticMarkup(<FullPreview title="Letter.pdf" data={{ kind: "pdf", url: "/api/documents/7/original" }} page={5} onClose={() => {}} />);
    expect(out).toContain('role="dialog"');
    expect(out).toContain("Letter.pdf");
    expect(out).toContain('href="/api/documents/7/original#page=5"');
    expect(out).toContain('src="/api/documents/7/original#page=5"');
    expect(out).toContain("Esc");
  });

  it("offers no new tab for a spreadsheet, which has no URL to open", () => {
    const out = renderToStaticMarkup(<FullPreview title="Returns.xlsx" data={{ kind: "grid", sheets: [{ name: "S1", rows: [["a", "1"]] }] }} onClose={() => {}} />);
    expect(out).not.toContain("Open in a new tab");
    expect(out).toContain('class="sheet"');
  });
});
