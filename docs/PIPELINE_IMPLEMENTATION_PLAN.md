# NHS GP Analytics — Pipeline Implementation Plan

> This document specifies the automated monthly data pipeline: how new NHS Digital publications are detected, downloaded, transformed, and committed to the repository, with full error handling and alerting.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Pipeline Architecture](#2-pipeline-architecture)
3. [Monthly Entry Point](#3-monthly-entry-point)
4. [GitHub Actions Workflows](#4-github-actions-workflows)
5. [Error Handling Strategy](#5-error-handling-strategy)
6. [NHS Digital URL Change Handling](#6-nhs-digital-url-change-handling)
7. [Alerting & Notifications](#7-alerting--notifications)
8. [Idempotency & Safety](#8-idempotency--safety)
9. [Testing the Pipeline](#9-testing-the-pipeline)
10. [Operational Runbook](#10-operational-runbook)

---

## 1. Overview

### What the pipeline does

On a monthly schedule, the pipeline:

1. Constructs the NHS Digital publication page URL for the current month
2. Scrapes the page to find the current download links (hash-prefixed, changes monthly)
3. Downloads and extracts the two target files (list size totals + mapping)
4. Transforms them into a consistent schema
5. Upserts the new month's data into the longitudinal Parquet files
6. Commits the updated Parquet back to the `main` branch
7. Streamlit Cloud auto-redeploys on the commit, making fresh data live

Enrichment assets (IMD and ONSPD) are maintained as Parquet and joined into mapping data as needed. ONSPD preprocessing uses DuckDB for large-file CSV scanning, filtering, and column projection.

### Scheduling rationale

NHS Digital publishes this dataset on approximately the **second Thursday of each month** at 09:30 GMT. The pipeline is scheduled for **10:30 UTC on the second Thursday** — 1 hour after the typical release window — to allow for occasional late publication. A daily retry workflow runs at 14:00 UTC for the rest of the month to catch delayed releases automatically.

---

## 2. Pipeline Architecture

```
GitHub Actions (cron)
        │
        ▼
pipeline/monthly.py
        │
        ├─► scraper.py       → fetch page HTML, resolve download URLs
        │       │
        │       ├─► 404 / Not found    → exit cleanly (not yet published)
        │       ├─► LinksNotFoundError → alert + create GitHub Issue
        │       └─► DownloadError      → retry workflow next day
        │
        ├─► extractor.py     → download ZIPs, extract CSVs
        │
        ├─► transformer.py   → normalise, type-cast, add SNAPSHOT_DATE
        │       │
        │       └─► TransformError    → alert + create GitHub Issue
        │
        ├─► loader.py        → upsert to list_size.parquet + mapping.parquet
        │
        ├─► scripts/extract_onspd_england.py  → preprocess ONSPD CSV to England-only parquet (DuckDB)
        ├─► scripts/prepare_imd_parquet.py    → preprocess IMD source to parquet
        └─► scripts/join_enrichment.py        → join enrichment parquet into mapping parquet
        │
        ├─► utils.py         → write pipeline_log.json
        │
        └─► git commit + push  → triggers Streamlit Cloud redeploy
```

      ### 2.1 Enrichment Processing Notes

      - IMD baseline is the latest 2025 release.
      - ONSPD source extracts are approximately 1.5GB and are preprocessed with DuckDB rather than pandas for scalable filtering/projection.
      - Enrichment artefacts are stored as Parquet to avoid repeated CSV parsing and to preserve typed columns across runs.
      - ONSPD extract includes both `lsoa11cd` and `lsoa21cd` so joins can accommodate IMD/code-vintage differences.

---

## 3. Monthly Entry Point

**File:** `pipeline/monthly.py`

```python
#!/usr/bin/env python3
"""
Monthly pipeline entry point.
Called by GitHub Actions; also runnable locally:
    python -m pipeline.monthly
    python -m pipeline.monthly --month december --year 2025
"""

from __future__ import annotations

import argparse
import sys
import logging
from datetime import date, datetime

from pipeline.config import PDS_START, MONTH_TO_INT
from pipeline.backfill import (
    MonthTarget, RunResult, make_session, build_page_url,
    fetch_with_retry, find_download_links, get_data_path,
    read_data_file, transform_list_size, transform_mapping,
    validate_practice_count, upsert_parquet, log_run,
    normalize_month, PageNotFoundError, LinksNotFoundError,
    DownloadError, ExtractionError, TransformError,
    DATA_PROCESSED, TOTALS_STEM, MAPPING_STEM,
)

log = logging.getLogger("monthly")


def run_monthly(target: MonthTarget, max_retries: int = 3) -> RunResult:
    """
    Single-month pipeline. Identical logic to backfill.process_month
    but with additional pre-flight checks appropriate for scheduled runs.
    """
    # Check: don't re-import if this month already exists (unless forced)
    from pipeline.backfill import get_ingested_snapshot_dates
    existing = get_ingested_snapshot_dates(DATA_PROCESSED / "list_size.parquet")
    if target.snapshot_date in existing:
        log.info(f"{target.label} already in Parquet — nothing to do.")
        return RunResult(month=target.month, year=target.year, status="skipped")

    session = make_session()

    # Re-use the same process_month from backfill for DRY consistency
    from pipeline.backfill import process_month
    result = process_month(target, session, max_retries=max_retries)
    log_run(result)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--max-retries", type=int, default=3)
    args = ap.parse_args()

    today = date.today()
    month_norm = normalize_month(args.month) if args.month else {
        1: "january", 2: "february", 3: "march", 4: "april",
        5: "may", 6: "june", 7: "july", 8: "august",
        9: "september", 10: "october", 11: "november", 12: "december",
    }[today.month]
    year = args.year or today.year

    target = MonthTarget(month=month_norm, year=year)
    result = run_monthly(target, max_retries=args.max_retries)

    if result.status == "failed":
        log.error(f"Pipeline failed for {target.label}: {result.error}")
        sys.exit(1)   # Non-zero exit triggers GitHub Actions failure + alerting

    log.info(f"Pipeline complete: {result.status} for {target.label}")


if __name__ == "__main__":
    main()
```

---

## 4. GitHub Actions Workflows

### 4.1 Monthly Scheduled Pipeline

**File:** `.github/workflows/monthly_pipeline.yml`

```yaml
name: Monthly NHS GP Data Pipeline

on:
  # Second Thursday of each month at 10:30 UTC
  # (NHS Digital typically publishes ~09:30 GMT on 2nd Thursday)
  schedule:
    - cron: '30 10 8-14 * 4'   # 4 = Thursday; day 8–14 = second Thursday

  # Manual trigger — for reruns, specific months, or testing
  workflow_dispatch:
    inputs:
      month:
        description: 'Month name or number (e.g. december, 12). Leave blank for current month.'
        required: false
        default: ''
      year:
        description: 'Year (e.g. 2025). Leave blank for current year.'
        required: false
        default: ''
      force:
        description: 'Force re-import even if month already in Parquet'
        required: false
        default: 'false'
        type: boolean

permissions:
  contents: write    # Required for git push
  issues: write      # Required for creating failure issues

jobs:
  ingest:
    name: Ingest latest GP practice data
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GH_PAT }}   # PAT with contents:write + issues:write
          fetch-depth: 1

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Resolve target month
        id: target
        run: |
          MONTH="${{ github.event.inputs.month }}"
          YEAR="${{ github.event.inputs.year }}"
          echo "month=${MONTH}" >> $GITHUB_OUTPUT
          echo "year=${YEAR}" >> $GITHUB_OUTPUT

      - name: Run pipeline
        id: pipeline
        run: |
          ARGS=""
          if [ -n "${{ steps.target.outputs.month }}" ]; then
            ARGS="--month ${{ steps.target.outputs.month }}"
          fi
          if [ -n "${{ steps.target.outputs.year }}" ]; then
            ARGS="$ARGS --year ${{ steps.target.outputs.year }}"
          fi
          python -m pipeline.monthly $ARGS
        env:
          PYTHONPATH: ${{ github.workspace }}

      - name: Check for Parquet changes
        id: changes
        run: |
          git diff --quiet data/processed/ && echo "changed=false" >> $GITHUB_OUTPUT \
            || echo "changed=true" >> $GITHUB_OUTPUT

      - name: Commit and push updated Parquet
        if: steps.changes.outputs.changed == 'true'
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/processed/ data/pipeline_log.json
          git commit -m "data: ingest ${{ steps.target.outputs.month || 'latest' }} ${{ steps.target.outputs.year || '' }} GP practice data [skip ci]"
          git push
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}

      - name: Create GitHub Issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const month = '${{ steps.target.outputs.month }}' || 'current';
            const year  = '${{ steps.target.outputs.year }}'  || new Date().getFullYear();
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo:  context.repo.repo,
              title: `🚨 Pipeline failed: ${month} ${year}`,
              body: [
                '## Monthly pipeline failure',
                '',
                `**Run:** [${context.runId}](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId})`,
                `**Month:** ${month} ${year}`,
                `**Triggered by:** ${context.eventName}`,
                '',
                '### Possible causes',
                '- NHS Digital has not yet published this month\'s data (check for 404)',
                '- NHS Digital changed the page layout or file stem (check for LinksNotFoundError)',
                '- Network / download failure (check for DownloadError)',
                '- Data format change in CSV (check for TransformError)',
                '',
                '### Next steps',
                '1. Check the [Actions log](' + context.serverUrl + '/' + context.repo.owner + '/' + context.repo.repo + '/actions/runs/' + context.runId + ') for error details.',
                '2. Check `data/pipeline_log.json` for the `error_type` field.',
                '3. If `LinksNotFoundError`: inspect the NHS Digital page and update `TOTALS_STEM` / `MAPPING_STEM` in `pipeline/config.py`.',
                '4. Re-run via Actions → Monthly NHS GP Data Pipeline → Run workflow.',
              ].join('\n'),
              labels: ['pipeline-failure', 'automated'],
            });
```

### 4.2 Daily Retry Workflow

**File:** `.github/workflows/daily_retry.yml`

```yaml
name: Daily Pipeline Retry

on:
  # Run at 14:00 UTC daily throughout the month
  # Catches delayed publications without requiring manual intervention
  schedule:
    - cron: '0 14 * * *'

  workflow_dispatch: {}

permissions:
  contents: write
  issues: write

jobs:
  check-and-retry:
    name: Retry if current month not yet ingested
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GH_PAT }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - run: pip install -r requirements.txt

      - name: Check if current month already ingested
        id: check
        run: |
          python - << 'EOF'
          import json, sys
          from datetime import date
          from pathlib import Path

          log_path = Path("data/pipeline_log.json")
          if not log_path.exists():
              print("No log found — running pipeline.")
              print("needs_run=true")
              sys.exit(0)

          with open(log_path) as f:
              records = json.load(f)

          today = date.today()
          current_key = (
              {1:"january",2:"february",3:"march",4:"april",5:"may",6:"june",
               7:"july",8:"august",9:"september",10:"october",11:"november",12:"december"}[today.month],
              today.year
          )
          for r in records:
              if (r.get("month"), r.get("year")) == current_key and r.get("status") == "success":
                  print("needs_run=false")
                  sys.exit(0)

          print("needs_run=true")
          EOF
        env:
          PYTHONPATH: ${{ github.workspace }}

      - name: Run pipeline if needed
        if: steps.check.outputs.needs_run == 'true'
        run: python -m pipeline.monthly
        env:
          PYTHONPATH: ${{ github.workspace }}

      - name: Commit if changed
        run: |
          git diff --quiet data/ || (
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add data/processed/ data/pipeline_log.json
            git commit -m "data: daily retry ingest [skip ci]"
            git push
          )
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}

      - name: Create issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `🚨 Daily retry failed: ${new Date().toISOString().slice(0,10)}`,
              body: `Daily retry pipeline failed. [View run](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId})`,
              labels: ['pipeline-failure', 'automated'],
            });
```

### 4.3 Manual Backfill Workflow

**File:** `.github/workflows/backfill.yml`

```yaml
name: Manual Backfill

on:
  workflow_dispatch:
    inputs:
      from_month:
        description: 'Start month (e.g. january)'
        required: true
        default: 'january'
      from_year:
        description: 'Start year'
        required: true
        default: '2019'
      to_month:
        description: 'End month (e.g. december)'
        required: false
        default: ''
      to_year:
        description: 'End year'
        required: false
        default: ''
      force:
        description: 'Force re-download of already-ingested months'
        required: false
        default: 'false'
        type: boolean

permissions:
  contents: write

jobs:
  backfill:
    runs-on: ubuntu-latest
    timeout-minutes: 180   # Historical backfill can take up to 3 hours

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GH_PAT }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - run: pip install -r requirements.txt

      - name: Run backfill
        run: |
          ARGS="--from-month ${{ github.event.inputs.from_month }} \
                --from-year ${{ github.event.inputs.from_year }} \
                --delay 2.5"
          if [ -n "${{ github.event.inputs.to_month }}" ]; then
            ARGS="$ARGS --to-month ${{ github.event.inputs.to_month }}"
          fi
          if [ -n "${{ github.event.inputs.to_year }}" ]; then
            ARGS="$ARGS --to-year ${{ github.event.inputs.to_year }}"
          fi
          if [ "${{ github.event.inputs.force }}" = "true" ]; then
            ARGS="$ARGS --force"
          fi
          python -m pipeline.backfill $ARGS
        env:
          PYTHONPATH: ${{ github.workspace }}

      - name: Commit results
        run: |
          git diff --quiet data/ || (
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add data/processed/ data/pipeline_log.json
            git commit -m "data: historical backfill ${{ github.event.inputs.from_year }}–${{ github.event.inputs.to_year || 'present' }} [skip ci]"
            git push
          )
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
```

---

## 5. Error Handling Strategy

### Error taxonomy and response

| Error Type | Cause | Pipeline Response | GitHub Issue Created? |
|------------|-------|-------------------|-----------------------|
| `PageNotFoundError` (404) | Month not yet published | Exit cleanly; daily retry will catch it | No |
| `PageNotFoundError` (historical) | Month pre-dates publication history | Log as `not_published`; skip | No |
| `LinksNotFoundError` | NHS Digital changed page layout or file stems | Hard fail; **issue required** | **Yes** |
| `DownloadError` | Network failure; server error | Retry up to 3× with backoff; then fail | Yes (after retries) |
| `ExtractionError` | Corrupt ZIP or unexpected file structure | Hard fail | Yes |
| `TransformError` | CSV schema changed (missing columns, bad types) | Hard fail | Yes |
| `ValidationWarning` | Practice count deviation >8% | Log warning only; continue | No |
| `ParquetWriteError` | Disk full or pyarrow error | Hard fail; old Parquet unchanged | Yes |

### Retry policy

```
Attempt 1: immediate
Attempt 2: wait 2^1 = 2 seconds
Attempt 3: wait 2^2 = 4 seconds
→ Total max wait before hard fail: ~6 seconds per file
→ GitHub Actions daily retry: next attempt 24 hours later
```

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| `0` | Success or clean skip (not yet published) |
| `1` | Hard failure — action required |

---

## 6. NHS Digital URL Change Handling

This is the highest-risk failure mode. NHS Digital occasionally:

- Renames file stems (e.g. `gp-reg-pat-prac-all` → new name)
- Changes page HTML structure (breaking BeautifulSoup selectors)
- Moves the publication to a new URL slug
- Switches from ZIP to direct CSV download (or vice versa)

### Detection

The scraper uses a two-stage approach:

**Stage 1 — Stem matching (primary):**
Search all `<a href>` tags on `files.digital.nhs.uk` for links containing `TOTALS_STEM` or `MAPPING_STEM` with `.zip` or `.csv` extension.

**Stage 2 — Text matching (fallback):**
Search anchor visible text for keywords: `"totals"`, `"list size"`, `"all persons"`, `"mapping"`. Log which fallback triggered for later debugging.

**Stage 3 — Structured failure:**
If neither stage resolves both files, `LinksNotFoundError` is raised with:
- The full page URL
- All `files.digital.nhs.uk` links found on the page (for manual inspection)
- A clear ACTION message in logs and the GitHub Issue

### Response procedure (manual)

When a `LinksNotFoundError` GitHub Issue is created:

1. Open the NHS Digital publication page for the relevant month
2. Right-click → View Source; search for `files.digital.nhs.uk`
3. Identify the new file stem(s) for totals and mapping
4. Update `pipeline/config.py`:
   ```python
   TOTALS_STEM = "new-stem-here"          # was: gp-reg-pat-prac-all
   MAPPING_STEM = "new-mapping-stem-here" # was: gp-reg-pat-prac-map
   ```
5. If page URL slug also changed, update `BASE_PAGE` in `config.py`
6. Commit and push; re-run the workflow via Actions → Run workflow

### Page URL slug change

If the publication moves (e.g. restructure under a new ministry):

1. Search NHS Digital for "patients registered GP practice"
2. Update `BASE_PAGE` in `pipeline/config.py`
3. The existing `find_download_links()` logic will work on the new page without changes

---

## 7. Alerting & Notifications

### GitHub Issues (primary)

All hard failures create a GitHub Issue with:
- Title: `🚨 Pipeline failed: {month} {year}`
- Body: run link, error type, likely causes, next steps
- Labels: `pipeline-failure`, `automated`

Issues are **not** auto-closed. Close manually after resolving and confirming the data was ingested.

### Email notifications (optional)

GitHub will email the repo owner when an Actions run fails by default. No additional config needed unless you want to route to a different address.

To add additional email alerting, add a step after the failure step:

```yaml
- name: Send email alert
  if: failure()
  uses: dawidd6/action-send-mail@v3
  with:
    server_address: smtp.gmail.com
    server_port: 465
    username: ${{ secrets.ALERT_EMAIL_USER }}
    password: ${{ secrets.ALERT_EMAIL_PASS }}
    to: your@email.com
    subject: "🚨 NHS GP Pipeline Failed: ${{ steps.target.outputs.month }}"
    body: "Pipeline failed. Check GitHub Issues for details."
```

### `pipeline_log.json` (in-repo audit trail)

Every run (success or failure) appends to `data/pipeline_log.json`. The dashboard sidebar reads this file to show:
- Date of last successful ingest
- Any months with failed status
- Total months in dataset

---

## 8. Idempotency & Safety

The pipeline is designed to be safely re-run at any time:

**Idempotent downloads:** If a file already exists in `data/raw/{YYYY}-{MM}-{month-name}/` (e.g. `data/raw/2026-04-april/`), it is not re-downloaded. Delete the raw directory to force a fresh download.

**Idempotent Parquet upsert:** If `SNAPSHOT_DATE + CODE` already exists in the Parquet, the existing rows are replaced (not duplicated). This handles NHS Digital's retroactive corrections correctly.

**`[skip ci]` on commits:** The pipeline commit message includes `[skip ci]` to prevent GitHub Actions from triggering again on the data commit (avoiding infinite loops).

**Parquet write safety:** The loader writes to a temp path first, then renames, so a failed write never corrupts the existing Parquet.

**No force-push:** All commits are standard pushes to `main`. No history is rewritten.

---

## 9. Testing the Pipeline

### Unit tests

```
tests/
├── test_scraper.py        # find_download_links with mock HTML
├── test_transformer.py    # transform_list_size, transform_mapping
└── test_loader.py         # upsert_parquet deduplication logic
```

**Key test cases for the scraper:**
- Standard page with stem-matching links → both found
- Page with renamed stems → Stage 2 text fallback triggered
- Page with neither → LinksNotFoundError raised
- HTTP 404 → PageNotFoundError raised
- HTTP 500 → retried, then DownloadError after max retries

### Local end-to-end test

```bash
# Test against a known historical month (safe to re-run)
python -m pipeline.monthly --month march --year 2024

# Dry run to see what backfill would do
python -m pipeline.backfill --from-month january --from-year 2024 --dry-run

# Force re-import of one month
python -m pipeline.monthly --month december --year 2025
```

### GitHub Actions test (manual trigger)

Go to Actions → Monthly NHS GP Data Pipeline → Run workflow → provide a specific month/year to test the end-to-end cloud pipeline without waiting for the schedule.

---

## 10. Operational Runbook

### Scenario: New month not showing in dashboard

1. Check `data/pipeline_log.json` — look for current month entry
2. If missing: NHS Digital may not have published yet. Check manually at:
   `https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice/`
3. If published but pipeline failed: check GitHub Issues for a failure report
4. Manual trigger: Actions → Monthly Pipeline → Run workflow (leave month/year blank)

### Scenario: `LinksNotFoundError` issue raised

1. Visit the publication page for the failed month
2. Find the actual download links in page source
3. Update `TOTALS_STEM` / `MAPPING_STEM` in `pipeline/config.py`
4. Commit change → Actions → Run workflow → specify the failed month/year
5. Close the GitHub Issue once confirmed ingested

### Scenario: Several months missing (e.g. after repo setup or config change)

```bash
# Locally: backfill specific range
python -m pipeline.backfill --from-month january --from-year 2025

# Via Actions: Actions → Manual Backfill → Run workflow
# Set from_month=january, from_year=2025
```

### Scenario: Parquet appears corrupt or has duplicate rows

```bash
# Inspect with DuckDB
python - << 'EOF'
import duckdb
con = duckdb.connect()
df = con.execute("""
    SELECT SNAPSHOT_DATE, COUNT(*) as n, COUNT(DISTINCT CODE) as unique_practices
    FROM 'data/processed/list_size.parquet'
    GROUP BY SNAPSHOT_DATE
    ORDER BY SNAPSHOT_DATE
""").df()
print(df.to_string())
EOF
```

If duplicates exist, force re-import the affected months with `--force`.

### Scenario: NHS Digital moves to a new URL structure

1. Search for the new publication home page
2. Update `BASE_PAGE` in `pipeline/config.py`
3. Test locally: `python -m pipeline.monthly --month december --year 2025`
4. Commit + push; no workflow changes needed
