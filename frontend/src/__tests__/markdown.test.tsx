import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Markdown from "../components/Markdown";

const html = (text: string, extra: any = {}) => renderToStaticMarkup(<Markdown text={text} {...extra} />);

describe("Markdown renderer", () => {
  it("renders bold, lists, numbered lists and tables", () => {
    const out = html("**Bold** text\n\n- one\n- two\n\n1. first\n2. second\n\n| A | B |\n|---|---|\n| 1 | 2 |");
    expect(out).toContain("<b>Bold</b>");
    expect(out).toContain("<ul>");
    expect(out).toContain("<ol>");
    expect(out).toContain("<table>");
  });
  it("turns citations into chips, with titles, pages and ranges", () => {
    const out = html("See [doc:12 p.4] and [doc:5 p.2-3] plus [obs:9] and [fact:3].", { labels: { 12: "Pipeline deck" } });
    expect(out).toContain("Pipeline deck");
    expect(out).toContain("p.4");
    expect(out).toContain("p.2-3");
    expect(out).toContain(">figure<");
    expect(out).toContain(">fact<");
    expect(out).not.toContain("[doc:12");
  });
  it("marks dropped citations and survives a half-streamed table", () => {
    expect(html("x [unverified] y")).toContain("unverified");
    expect(() => html("|")).not.toThrow();
    expect(html("partial", { caret: true })).toContain("caret");
  });
});
