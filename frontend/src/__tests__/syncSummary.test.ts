import { describe, expect, it } from "vitest";
import { describeSync, summarizeTick } from "../lib/syncSummary";

describe("describeSync", () => {
  it("says the sync's report in words", () => {
    expect(describeSync([{ listed: 16, new: 0, changed: 0, unchanged: 16, removed: 0, pending: 12, at: "2026-10-27T18:06:34" }]))
      .toBe("Synced just now: 16 files in the folder, nothing new, 12 files waiting to be read.");
    expect(describeSync([{ listed: 3, new: 1, changed: 1, removed: 1, pending: 1 }]))
      .toBe("Synced just now: 3 files in the folder, 1 new file, 1 changed file, 1 file removed, 1 file waiting to be read.");
    expect(describeSync([{ listed: 1, new: 0, pending: 0 }])).toBe("Synced just now: 1 file in the folder, nothing new, everything read.");
  });

  it("sums several folders and survives an empty or odd result", () => {
    expect(describeSync([{ listed: 2, pending: 1 }, { listed: 3, new: 2 }])).toBe("Synced just now: 5 files in the folder, 2 new files, 1 file waiting to be read.");
    expect(describeSync([])).toBe("Synced. Nothing to report.");
    expect(describeSync(undefined)).toBe("Synced. Nothing to report.");
  });
});

describe("summarizeTick", () => {
  it("keeps the folder card's counts short and adds the queue only when there is one", () => {
    expect(summarizeTick({ listed: 16, new: 0, changed: 0, removed: 0, pending: 12 })).toBe("16 listed · 0 new · 0 changed · 0 removed · 12 waiting");
    expect(summarizeTick({ listed: 2, new: 1, changed: 0, removed: 0, pending: 0 })).toBe("2 listed · 1 new · 0 changed · 0 removed");
    expect(summarizeTick(null)).toBe("—");
  });
});
