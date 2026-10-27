import { describe, expect, it } from "vitest";
import { baseName, docTypeLabel, flagText, metricLabel, statusLabel } from "../lib/labels";

describe("plain-language labels", () => {
  it("translates statuses for the team and keeps codes for IT", () => {
    expect(statusLabel("needs_review", "team")).toBe("Needs a look");
    expect(statusLabel("rejected", "team")).toBe("Not allowed (personal ID)");
    expect(statusLabel("needs_review", "it")).toBe("needs review");
  });
  it("translates document types, metrics and flags", () => {
    expect(docTypeLabel("term_sheet", "team")).toBe("Rates & terms");
    expect(docTypeLabel("term_sheet", "it")).toBe("term_sheet");
    expect(metricLabel("mgmt_fee", "team")).toBe("Management fee");
    expect(flagText({ code: "missing_as_of", msg: "x" }, "team")).toMatch(/as-of date/);
    expect(flagText({ code: "missing_as_of", msg: "x" }, "it")).toBe("missing_as_of: x");
  });
  it("strips file extensions for display", () => {
    expect(baseName("Northwind_Factsheet.pdf")).toBe("Northwind_Factsheet");
    expect(baseName("no-extension")).toBe("no-extension");
  });
});
