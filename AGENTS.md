# AGENTS.md

Flask API that extracts SAP Requisition (REQ) data from base64 PDFs. Deployed to Heroku.

## Commands
- Install: `pip install -r requirements.txt`
- Run server: `python test_local.py --server` (or `python app.py`); port from `PORT`, default 5000.
- Test one PDF: `python test_local.py path/to/REQ.pdf` — prints parsed fields, writes `<name>_result.json`, and simulates the HTTP roundtrip.
- Test all: put PDFs in `./pdfs/` then `python test_local.py`.
- Production entrypoint: `gunicorn app:app` (see `Procfile`), Python 3.11.9 (`runtime.txt`).

## Testing reality
- There is no pytest/unittest suite, linter, or CI. `test_local.py` is a manual script.
- `pdfs/` and `*_result.json` are gitignored, so a fresh clone has no fixtures. Ask the user for sample PDFs before validating parser changes; never invent fixtures.

## Parser architecture (`app.py`)
- `POST /extract` accepts `{filename?, content: <base64>}`; strips an optional `data:` URI prefix. Returns 400 on missing/invalid base64, 422 on scanned/undetected PDFs.
- PDFs are read with `pdfplumber` using `extract_text(layout=True)`; the layout-preserved text is essential because items are parsed line-by-line with column positions.
- `_is_plan_req` requires `PLAN`, `INTERNATIONAL`, `REQUISITION` in the text (uppercased).
- Header fields are read only from `pages[0]` (the header repeats on every page); items, total, and observations still scan the full text.
- `ITEM_RE` matches an item line; `TAIL_RE` matches delivery date, GL account, cost center, and optional WBS. Changes here are high-risk.
- `ITEM_TEXT_RE` captures the `ITEM TEXT:` block into `ItemText`; it is assigned to the last parsed item because a page break can place that block after the next page header (México uses this field, other countries leave it empty).
- Country-specific quirks are intentional and fragile:
  - Rep. Dominicana: delivery date can be glued to the valuation with no space (`3.700.000,0011.12.2025`).
  - Cost center can be split across the item line and the next line (e.g. `PRJDODOM` + `1`), detected by column zone (`desc_end_col = 65`).
  - WBS may land on the continuation line.
  - México: currency `MXN`; the Material Master column can prefix the description with a code such as `HIFH21NC1`.
- Validate regex/parser edits against PDFs from Paraguay, Perú, Rep. Dominicana, and México, not just one.
- `_parse` must keep `items` as a JSON list. The commented-out `json.dumps` lines are deliberate experiments; don't re-enable them casually (Power Automate consumes the JSON).
- `summary.Observations` is free text after the last `Total Value`; numeric-only lines are skipped.

## Conventions
- Code, comments, and user-facing messages are in Spanish; keep that style.
- No dependency/config changes beyond the pinned versions unless requested; Heroku builds from `requirements.txt`.
