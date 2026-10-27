# Walkthrough

The walkthrough ships inside the app as an interactive tutorial (`frontend/src/components/Tour.tsx`; *Tutorial* button in the header). The outline below is the same story, kept as a script in case a recorded version is ever wanted.


Target: the brief's own sentence. "I connect my Google Drive, point it at a folder with 20 messy PDFs from different fund managers, and I can immediately see a table of all extracted performance data, filter by fund or date, and ask 'Which fund had the best January return?' — and when a new factsheet lands in the folder, it's processed automatically."

Before recording
- `.env` has OPENROUTER_API_KEY + Google client; server running; corpus generated; the Drive folder "DocIntel Demo" holds the corpus EXCEPT one file (keep `Northwind_GlobalMacro_Factsheet_Sep2026.pdf` on the desktop to drop in live).
- Database empty (`rm data/docintel.db`), restart, so the sync is visibly the thing that fills it.
- Browser at 1280 wide, zoom 110 %.

0:00 – 0:35  The shape (one breath, on the Connect page)
"Drive folder in, one queryable table out. Sync every minute diffs the folder; each file goes to Claude as the file itself, with one strict schema; figures land in a long fact table with the verbatim evidence; questions are answered through a read-only SQL tool you can audit."

0:35 – 1:20  Connect
Click Connect Google Drive → consent → back. Search "DocIntel", pick the folder. Point at the sync card: watching, last tick, counts. Click Sync now once.

1:20 – 2:30  Documents fill in
Switch to Documents; rows appear as the pool finishes them (3 in parallel). Open the Sable Ridge two-column factsheet: figures table, the evidence column with ✓ "found in text", confidence, the Document text tab. Open the Meridian scan: "image-only PDF" chip, evidence marked "scanned" rather than faked. Open the holiday schedule: classified other, flagged, nothing invented.

2:30 – 3:10  Data
Stats tiles. Filter metric = return, period = month, month = Jan: Sable Ridge 3.87 on top for 2026, Northwind 4.10 for 2025 (the CSV). Clear, filter by manager. Export CSV.

3:10 – 4:00  Ask
"Which fund had the best January return?" Read the answer: it names the year. Expand "How it was answered": the SQL, the rows, the citations. One more: "What is Harbor Point's Q3 return versus its benchmark?"

4:00 – 4:35  The new file lands
Drag the Northwind September factsheet into the Drive folder. Back to Documents; within the next tick it appears as pending → extracting → done. Note the August edition is still there and the Ask answer can tell the two apart by as-of date.

4:35 – 5:00  Decisions and limits
Model reads PDFs (no parser per layout); every field required; evidence verified; SQL tool allowlisted twice; polling over push; Testing-mode tokens expire in 7 days; next: changes.list, fund merge, column-mapping for big CSVs, eval against answer_key.json.
