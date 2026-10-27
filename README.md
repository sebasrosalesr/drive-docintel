<div align="center">

# Drive DocIntel

**Point it at a Google Drive folder of messy fund documents. Get one queryable table, with every number traced back to the line it came from.**

![Python 3.12](https://img.shields.io/badge/Python-3.12-0B1424?labelColor=0B1424&color=C9A84C) ![FastAPI](https://img.shields.io/badge/FastAPI-SQLAlchemy_2-0B1424?labelColor=0B1424&color=C9A84C) ![React 18](https://img.shields.io/badge/React_18-Vite-0B1424?labelColor=0B1424&color=C9A84C) ![Claude via OpenRouter](https://img.shields.io/badge/Claude-via_OpenRouter-0B1424?labelColor=0B1424&color=C9A84C) ![tests](https://img.shields.io/badge/tests-68_pytest_·_11_vitest-0B1424?labelColor=0B1424&color=C9A84C)

</div>

**Drive DocIntel** is a document intelligence web app for fund documents. It connects to Google Drive, watches a folder, reads every factsheet, statement, report, email and spreadsheet that lands there with an LLM, and turns them into one table you can filter, search and question, every figure traced to the line it came from. Built for Equi's take-home (Option A). **Walkthrough:** instead of a video, the app carries an interactive tutorial. It starts on first visit and can be replayed from the *Tutorial* button in the header: thirteen spotlight steps across Connect, Documents, Data and Ask, each with the decision behind it, and two live actions (open a document, ask the January question). On an empty library it offers to load the 13-document sample corpus with one click.

## What it does

1. **Connect** Google with OAuth and pick a folder (or paste its URL).
2. **Sync** runs every 60 s and on demand: every PDF, image, HTML email, `.eml` (and its attachments), CSV, Excel, Word, PowerPoint, Google Doc or Sheet in the folder tree is diffed against what was already read. New or changed files are processed; files that disappear are retired. The same watcher can point at a folder on the machine (`WATCH_DIR`), and the Documents page takes drag-and-drop uploads.
3. **Screen, then extract**: a local PII gate rejects identity documents before anything is sent and masks SSN / card / account numbers in the rest. Then one prompt and one strict JSON schema for every document, whatever it is. PDFs and images go to the model as PDFs/images (it reads the page, so there is no per-layout parser and scans work). HTML, email, CSV, Excel, Word and PowerPoint are rendered to text. Every document gets a **title, a plain-English summary and key points**; performance figures come back as `fund · metric · period · value · unit · basis`; everything else with a value (minimums, target sizes, rates, closing dates, terms) comes back as **facts**. Each figure and fact carries a **verbatim evidence fragment** and a confidence.
4. **Store** in a long fact table (`observations`) under SQLAlchemy. SQLite locally, Postgres in the cloud. Validation flags (ranges, dates, months that don't compound to the stated year, unverifiable evidence) send a document to `needs_review` instead of silently accepting it.
5. **Browse** documents and figures, filter by fund / manager / metric / period, open a document to see the **original in its own form** (PDF viewer, spreadsheet grid for CSV and Excel, a Word-style page, an email view) next to each number and the line it was read from, export CSV. Everything is in plain language by default ("Fund factsheet", "Needs a look: no as-of date was found"); a technical view with status codes, model, cost, engine, extracted text, raw JSON and *re-run with model B* is one URL parameter away (`?view=it`). Each document also keeps its **History** (every reading, with a diff), and near-duplicate fund names can be merged from the Data page.
6. **Ask the library** in plain English, as a chat with memory. The model sees the registry (one line per document in its context) and three tools: `search_documents` (passages across titles, summaries, key points, facts and page text), `read_document` (summary, facts and up to six pages of text), and `run_sql` (read-only views of figures and facts). Answers stream token by token (`POST /api/ask/stream`, NDJSON events) and cite `[doc:N p.3]`, `[fact:N]`, `[obs:N]`; every citation is audited against what the tools returned, the source documents are listed under the answer, and clicking one opens the original at that page.

```
Drive folder · local folder · upload ──sync (60 s)──▶ files ──▶ render (+ OCR tiers) ──▶ PII gate ──▶ model (strict JSON schema) ──▶ normalize + validate
                                                                                                                                              │
   Connect · Documents · Data · Ask  ◀──── FastAPI /api ◀──── search_documents · read_document · run_sql ◀──── documents · funds · observations · facts
```

## Quick start (local, no Google needed)

```bash
git clone <this repo> && cd drive-docintel
python3.12 -m venv .venv && . .venv/bin/activate      # 3.12
pip install -r requirements-dev.txt
brew install tesseract poppler                         # optional: OCR tiers for scans (apt: tesseract-ocr poppler-utils)
cp .env.example .env                                   # set OPENROUTER_API_KEY (everything else has defaults)
pytest                                                 # 68 tests, no network (set DATABASE_URL to run them against Postgres)

python scripts/make_corpus.py --out corpus             # 13 synthetic documents (PDF, scan, HTML, CSV, Excel, Word) from 5 fictional managers + answer_key.json
python scripts/run_local.py corpus                     # runs them through the same pipeline the Drive sync uses (~$0.85 with the default Opus reader; ~$0.46 with --model google/gemini-4-argon)
python scripts/eval_extraction.py corpus/answer_key.json   # recall / precision / evidence table
(cd frontend && npm test)                              # 11 vitest tests: labels, Markdown, the sync summary, the full-window preview

(cd frontend && npm ci && npm run build)
uvicorn docintel.main:app --port 8080                  # open http://localhost:8080 — the tutorial starts on first visit
```

The Documents, Data and Ask pages work on the locally ingested corpus. `scripts/run_local.py` is the pipeline without Drive, which is also how to re-test extraction after changing the prompt.

## PII gate

Before any model call, the extracted text (or local OCR for images and scans) is screened on this machine:

- **Identity documents** (driver's licence, passport, ID card, Social Security card, birth certificate) are **rejected**: nothing is sent to the model, no text or original is kept, the row shows why. `PII_IDENTITY_POLICY=allow` turns this off.
- **Sensitive identifiers inside ordinary documents** (SSN/ITIN, card numbers that pass Luhn, routing and account numbers) are **masked** (`[REDACTED SSN]`, `[CARD ••••1111]`) and the model receives the masked text instead of the original file. `PII_REDACT=0` turns this off.

Detection is deliberately local and rule-based (keyword scores plus patterns, `docintel/pii.py`), so the decision never depends on sending the document anywhere.

## Watch a folder on your own machine (no Google needed)

Set `WATCH_DIR=/path/to/folder` in `.env` and restart. The same sync loop scans it every minute (and on *Sync now*): new or changed files are read, deleted files are retired. The Documents page also has an *Add documents* drop zone for one-off files.

## Google Drive setup (10 minutes)

The app signs people in with Google and reads their Drive with the read-only scope. One OAuth client serves local and deployed; the consent screen stays in *Testing* for a demo.

1. Google Cloud console, a project (the deployed instance uses the same project as the Cloud Run service): **APIs & Services → Library → enable "Google Drive API"**.
2. **OAuth consent screen**: External, publishing status *Testing*. Scopes: `.../auth/drive.readonly`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `openid`. Under **Test users** add every Google account that will sign in: yours and each reviewer's. Testing mode admits only listed accounts; anyone else sees Google's "access blocked" page. Publishing instead would mean Google's verification review for the Drive scope, weeks of work, so a demo stays in Testing.
3. **Credentials → Create → OAuth client ID → Web application**, with both redirect URIs:
   - `http://localhost:8080/api/auth/google/callback`
   - `https://<your service URL>/api/auth/google/callback`
4. Put the client id and secret in `.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (download the client JSON from the console; the two values are `web.client_id` and `web.client_secret`), restart, open the Connect page.

What a test user sees on first sign-in: Google's "hasn't verified this app" screen. *Advanced → Go to Drive DocIntel* continues; then the Drive consent; then the Connect page to pick a folder. Testing-mode consent expires after 7 days; the app notices the failed refresh and shows a *Reconnect* button. Every signed-in account gets its own Drive connection and watched folder; the document library is shared. *Disconnect Drive* on the Connect page forgets the account, its token and its folder; documents already read stay.

Two traps the sign-in flow handles, both met in production: the Google OAuth library (1.2+) generates a PKCE code verifier when the sign-in URL is built and wants it back at the token exchange, which runs in a different request, so the verifier rides the signed state cookie (`docintel/auth.py`); and `httplib2`, which the Google API client speaks through, is not thread-safe, so the Drive client hands each extraction worker its own authorized transport with a timeout (`docintel/drive.py`). Without the second, three downloads starting together ended as one "SSL record layer failure" and two silent hangs.

## Deploy

Frontend and backend are one service: the container serves the API and the built app from the same origin (no CORS, one OAuth redirect URL). The live demo runs exactly this shape on Google Cloud, with the database on Neon:

| Piece | Where | Why |
|---|---|---|
| App (API + UI) | Cloud Run, service `docintel`, one always-on instance (`min=max=1`, CPU not throttled), 1 vCPU / 1 GiB | the Drive watcher runs in-process; scale to zero + Cloud Scheduler if you prefer (commands in the script) |
| Database | Neon Postgres, its own database (`docintel`) in an existing Neon project, through the **pooled** endpoint | Cloud Run's disk is wiped on restart, so SQLite is local-only. Neon's pooler is PgBouncer in transaction mode, where a prepared statement cached by one client is an "already exists" error for the next: `docintel/db.py` sets psycopg's `prepare_threshold=None` on Postgres |
| Originals, sample corpus | a Cloud Storage bucket (`<project>-docintel-data`) mounted at `/mnt/data` (`DATA_DIR`) | keeps "open original" and re-reads working across restarts |
| Secrets | Secret Manager: `OPENROUTER_API_KEY`, `GOOGLE_CLIENT_SECRET`, `APP_SECRET`, `DATABASE_URL`, `APP_PASSWORD` | the service account reads them at start; nothing sensitive is in the image or the env vars |
| Public access | `--allow-unauthenticated`, or, where an organisation policy forbids `allUsers`, Cloud Run's *invoker IAM check disabled* | the app's own `APP_PASSWORD` gate is the lock either way |
| Models | reader `MODEL=anthropic/claude-opus-5.5`, fallback `google/gemini-4-argon`, Ask `anthropic/claude-opus-5.5`, `TABLE_REASONING_EFFORT=low` | the demo's settings; a big spreadsheet reads in 30–40 s for ~$0.20, a small one in under 10 s for ~$0.03 |

```bash
# .env: DATABASE_URL (Neon, pooled host), GOOGLE_CLIENT_ID/SECRET, OPENROUTER_API_KEY, APP_SECRET, APP_PASSWORD
gcloud auth login                                     # an owner of the project
PROJECT=<gcp-project> REGION=us-central1 SERVICE=docintel bash deploy/cloud_run.sh
```

The script enables the APIs (Run, Cloud Build, Artifact Registry, Secret Manager), creates the Artifact Registry repo and the bucket, stores or re-versions the secrets from `.env`, builds the image with Cloud Build (about six minutes: the Node build of the SPA, then Python with Tesseract and poppler), deploys with the bucket mounted, and prints the URL to add to the OAuth client's redirect URIs. Google OAuth and the app password are optional: without the Google secret the app still takes uploads and a local folder.

Things that bit while standing the demo up, so you don't have to meet them:

- **Enable the Drive API in the same project** as the OAuth client, or the consent step fails with a cryptic error.
- **Organisation policy `iam.allowedPolicyMemberDomains`** (common on Workspace-owned projects) refuses the `allUsers` invoker binding, so `--allow-unauthenticated` deploys the service but it answers 403. The fix is one command, after the deploy: `gcloud run services update docintel --no-invoker-iam-check --region us-central1`. It survives later deploys.
- **Create the Neon database first** and point `DATABASE_URL` at it (`postgresql://user:pw@<pooled-host>/docintel`); the app creates its tables on first start. Keep it a separate database from anything else in the Neon project.
- **Each deploy re-versions every secret from the machine's `.env`**, the app password included. With two machines deploying, keep their `.env` files in step or the password changes under you.
- **Firebase Hosting in front of Cloud Run was not used on purpose**: Hosting strips every cookie except one reserved name, and the app signs in with three. The Cloud Run URL serves the SPA itself.

## Decisions worth explaining

- **The model reads the PDF, not a parser.** Every manager's factsheet is laid out differently; text extraction then regex is a parser per layout in disguise. Sending the PDF itself (OpenRouter `file-parser` plugin, engine `native` → Claude's PDF input) handles tables, prose, two-column pages and scans with one prompt. pypdf text is kept only for the raw-text tab and for verifying evidence. If a scan returns nothing natively, the pipeline retries once with `mistral-ocr`.
- **One strict schema for every kind of document, every field required.** Optional/union fields are capped in Anthropic strict mode and make storage branchy; sentinels (`""`, `"unknown"`, `0`) keep the shape fixed. `tests/test_schema_strict.py` fails if someone adds an `Optional`.
- **Evidence is verbatim and checked.** The model must quote the fragment containing each value; `normalize.verify_evidence` looks for it on the cited page first, then in the whole document: exact after normalisation (whitespace, dashes, `%`), then fuzzy ≥ 0.85, then a numbers-and-a-word match for table rows that extraction reflows onto separate lines. Unverified fragments show as ✗ in the UI and, above 30 % of the checkable ones, flag the document for review. Pages with no text layer are marked `image-page` / `scanned` rather than counted against the document.
- **Text is tiered per page, like a proper OCR pipeline.** `pdftotext -layout` (keeps table rows on one line) or pypdf, then pdfplumber for thin pages, then Tesseract for pages with no text at all. The model still reads the original; this text exists for verification, search and the raw-text tab. Tesseract and poppler are in the Docker image; locally `brew install tesseract poppler`.
- **Long fact table, explicit period columns.** `period_type / period_year / period_month / period_start / period_end` make "best January return" a WHERE clause instead of date arithmetic, and keep Jan 2025 and Jan 2026 apart. `basis` (net/gross/unknown), `share_class` and `currency` are first-class so the Ask prompt can refuse to compare unlike things.
- **Ask = registry + three tools + audit.** The library digest in the prompt lets the model pick documents by id; `search_documents` is a small term-overlap ranker over per-page text (no vector store needed at this scale); `read_document` is bounded to ~6 pages a call; `run_sql` is allowlisted at the SQL level (SELECT only, only `v_observations`, `v_documents`, `v_facts`, `funds`, one statement, LIMIT) and again by the database (SQLite authorizer that denies `ATTACH`, `PRAGMA`, other tables and `raw_text`; Postgres read-only transaction with a statement timeout). Citation markers are kept only if the id appeared in a tool result; anything else is shown as *unverified*. For a BigQuery shop the most legible answer is still the query, and it is shown.
- **Large spreadsheets never go to the model row by row.** Above ~120 rows, one call sees the header, a dozen sample rows and per-column summaries and returns a *column mapping* (`docintel/tabular.py`); code applies it to every row, so a 10,000-row export costs the same as a 100-row one and the rows themselves stay on the machine.
- **Polling over push.** A recursive `files.list` every minute is a handful of quota units and gives removals for free. Dedupe key is `md5Checksum` for binaries and `version + modifiedTime` for Google-native files (which have no md5); `sha256(bytes)` dedupes identical content. The upgrade path is `changes.list` with a stored page token; push notifications need a public HTTPS endpoint and weekly channel renewal and were not worth it here.
- **Idempotent, inspectable failures.** A file is `pending → extracting → done | needs_review | failed | skipped | rejected`. Failures keep the error on the row, cost and tokens are logged per call, originals are kept so *Re-run extraction* works, and a crash mid-extraction is reset after 15 minutes.
- **Prompt injection.** Document content is wrapped as data in the user turn with an explicit rule; the model is asked to report embedded instructions as warnings. The SQL tool never sees document text except as cell values, which the Ask prompt treats as data.

## Layout

```
docintel/            FastAPI app
  config.py db.py models.py            settings · engine, migrations and the three read views · SQLAlchemy models
  schema.py prompts.py llm.py          extraction + table-mapping schemas · prompts · OpenRouter client (streaming, cost cap, injectable transport)
  render.py preview.py                 bytes→text with OCR tiers (PDF, image, HTML, .eml, CSV, XLSX, DOCX, PPTX) · native previews for the drawer
  pii.py                               local PII gate: identity documents rejected, identifiers masked
  tabular.py                           column mapping applied to every row of large spreadsheets
  normalize.py validate.py             fund identity, periods, evidence verification · sanity flags
  pipeline.py                          one file: render → gate → model → normalize → validate → persist (+ email attachments)
  sync.py drive.py localfolder.py auth.py   Drive diff + scheduler · Drive API · local watched folder · Google OAuth + app password
  ask/registry.py ask/guard.py ask/agent.py library digest, passage search, page reader · read-only SQL guard · tool loop + citation audit
  api/                                 ask_routes · auth_routes (app password, Google sign-in, Disconnect Drive) · data_routes (documents, facts, funds, export, re-run, escalate, tutorial, upload) · drive_routes (folders, sync)
frontend/            Vite + React + TypeScript: Connect, Documents, Data, Ask chat; Tour (interactive tutorial), Loaders (GSAP status glyphs), DocumentDrawer, Preview, Markdown; palette and type follow equi.com (forest #0f2319, lime #dff9ba, golden beige #c9b69a, ingot gold #e0a920, cream #f8f6f1; Inter + Newsreader standing in for Untitled Sans + Rizoma), all as CSS variables in `src/styles.css`
scripts/             make_corpus.py · run_local.py · eval_extraction.py · gold_export.py · eval_gold.py · reverify.py · seed_fake.py (dev only)
tests/               68 pytest tests (SQLite by default, Postgres via DATABASE_URL), no network; frontend: 11 vitest tests
docs/                DEMO_SCRIPT.md (the tour as a script) · loader-preview.html
deploy/cloud_run.sh  APIs, bucket, secrets, build, deploy
```

## Measured on the synthetic corpus

`scripts/eval_extraction.py` scores the database against `corpus/answer_key.json` (every monthly return and key statistic the documents print). Same prompt, same schema, two models through OpenRouter, the 11 original documents (the Excel and Word files added later also score 100 %):

| | `anthropic/claude-opus-5.5` | `google/gemini-4-argon` |
|---|---|---|
| Monthly returns recalled | 58/58 | 58/58 |
| Extracted monthly rows equal to the truth | 107/107 | 107/107 |
| Key statistics (AUM, fees, Sharpe, vol, drawdown) | 27/27 | 27/27 |
| Evidence fragments found verbatim in the text | 143/143 (text documents) | 142/142 |
| Image-only scan | read natively, 16 figures, evidence marked `scanned` | same |
| Total cost, 11 documents (before the Excel and Word files were added) | $0.85 | $0.46 |
| Mean time per document | 40 s | 47 s |
| Documents flagged for review | 3 (two CSVs lack a manager or as-of date; one non-financial PDF) | 2 (it dated the wide CSV from its "Sep-26" column) |

Defaults: `MODEL=anthropic/claude-opus-5.5` for extraction (model A) and `FALLBACK_MODEL=google/gemini-4-argon` as model B (OpenRouter routes to it if A fails, and every document drawer has *Re-run with model B* so a disputed document can be read twice), `ASK_MODEL=anthropic/claude-opus-5.5` for the Ask loop where SQL judgement matters. The two score the same on the corpus; Gemini is cheaper per document and Opus was the steadier reader on real spreadsheets, so the demo reads with Opus. Spreadsheets and CSVs run at `TABLE_REASONING_EFFORT=low` (a few seconds to under a minute); PDFs at `REASONING_EFFORT=medium`. Re-run the comparison with `python scripts/run_local.py corpus --force --model <slug>` against a scratch `DATABASE_URL`.

Example Ask, real run: *"Which fund had the best January return?"* → "Sable Ridge Equity Long/Short, +3.87% net in January 2026 (most recent year; two documents report it) … the only January 2025 figure is Northwind Class A at +4.10%", with a table of all five funds, one query, every number cited, 10 seconds, 2.5 cents.

## Gold set for real documents

`python scripts/gold_export.py <doc ids>` writes one JSON per document with its current figures and facts; correct them by hand (they stay local: `gold/` is git-ignored because it holds your documents' contents), and `python scripts/eval_gold.py` scores every later reading against them (recall and precision for figures and facts, plus type / as-of checks). That is how prompt or model changes get measured on your own documents rather than on the synthetic corpus.

## Operations

- `TABLE_REASONING_EFFORT` (default `low`) is the think a spreadsheet or CSV gets; PDFs and prose keep `REASONING_EFFORT`. A small spreadsheet read in 25 s at medium and under 10 s at low; a large one in 30–40 s.
- `APP_PASSWORD` locks every API route behind a sign-in screen (for a deployed demo). `DAILY_COST_CAP_USD` stops model calls once today's spend reaches the cap (`0`, the demo's setting, means no cap); the Connect page shows the reader version with "Re-read everything" / "Re-read the outdated" buttons (the demo shows no spend figure).
- **Starting over** (a fresh test run on the deployed demo): truncate `observations, facts, llm_calls, documents, drive_files, local_files, funds, watched_folders` with `RESTART IDENTITY CASCADE`, keep `users` and `google_accounts` so sign-ins survive, and empty the bucket. The Connect page then offers the folder picker again and nothing re-reads until a folder is chosen. From the UI, *Disconnect Drive* on the Connect page is the per-account version of this.
- **Send to engineering**: a document in `needs_review` or `failed` has a button that pings the engineering team to ingest it from their end, one Slack-shaped POST to `ESCALATION_WEBHOOK_URL` with the file, the validator's reasons and the link. The demo leaves the URL unset on purpose: the button then shows the message it would have sent, and nothing leaves.
- **A stuck read**: a row left in `extracting` by a restart resets itself after 15 minutes; a `failed` row stays failed until re-run from the document's drawer or set back to `pending` on the database.
- Document **History** (drawer tab) lists every reading of a file with a diff of figures against the previous one. **These look like the same fund** (Data page) suggests duplicate funds and merges them with one click, keeping the other name as an alias.
- `.eml` attachments (PDF, CSV, Excel, Word…) are read as their own documents, linked to the email.

## Known limits and next steps

- Fund identity is a normalised-name match with aliases; the duplicates panel catches the rest but needs a human click.
- Legacy `.xls` / `.doc` / `.ppt` are skipped (`.xlsx` / `.docx` / `.pptx` work). Images (PNG, JPG, WebP, TIFF) are read as scans.
- One app password and one shared library: every signed-in Google account has its own Drive connection and watched folder, but sees every document, and there are no per-user roles or per-document permissions.
- Drive `changes.list` instead of listing, Cloud Scheduler instead of the in-process loop (commands in `deploy/cloud_run.sh`), and a BigQuery export of `observations` would be the production shape.

Nothing in `corpus/` is real: five fictional managers, generated numbers.
