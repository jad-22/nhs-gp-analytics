# Local Monthly Refresh

The monthly ingestion runs from a scheduled task on a local machine rather than from GitHub
Actions. This document covers why, and how to set it up.

## Why not GitHub Actions

Cloudflare sits in front of `digital.nhs.uk` and returns **403 to GitHub-hosted runners on every
attempt**, regardless of User-Agent. The July and August 2026 scheduled runs both died at
`fetch_html`. The same request from a residential IP returns 200:

| Source | User-Agent | Result |
| --- | --- | --- |
| GitHub-hosted runner | `nhs-gp-analytics/1.0` | 403 |
| Residential IP | `nhs-gp-analytics/1.0` (identical) | 200 |
| Residential IP | Chrome desktop | 200 |
| Residential IP | bare `curl/8.x` | 200 |

Since User-Agent makes no difference, the discriminator is the source IP — bot management scoring
the runner's Azure range. Retries do not help much: they all originate from the same runner IP
inside a few seconds. The retry logic added alongside this change is still worth having (it turns a
raw traceback into a logged `failed` result) but it is not the fix.

Scraping cannot be skipped either. Download URLs carry an opaque per-file segment that changes every
month and differs between the two files in one publication:

| Month | totals (`-all`) | mapping (`-map`) |
| --- | --- | --- |
| Aug 2026 | `/45/E255E0/` | `/26/656B2E/` |
| Jul 2026 | `/0C/C6EF77/` | `/98/8142DB/` |
| Jun 2026 | `/15/4E45A6/` | `/8B/68C830/` |

There is no derivable pattern, so the publication page has to be read to discover them.

A self-hosted Actions runner would solve the IP problem while keeping the workflow intact, but this
repository is public, and GitHub advises against self-hosted runners on public repositories: a fork
PR can execute arbitrary code on the runner host.

Only the scrape needs a residential IP. `build_dashboard_cache.py` and `build_forecast_cache.py`
make no network calls at all, so everything downstream of ingestion can stay in CI.

## What the task does

1. Hard-reset a dedicated clone to `origin/main`.
2. Exit early if the target month is already recorded as `success` there.
3. `python -m pipeline.monthly` — scrape, download, transform, upsert.
4. `python scripts/join_enrichment.py` — **required**, see below.
5. `python scripts/build_dashboard_cache.py --skip-anomalies`.
6. Commit `data/processed/` and `data/pipeline_log.json`, push to `main`.

Step 4 is easy to overlook and was missing from the original workflow. `pipeline.monthly` writes the
new month's mapping rows straight from the NHS extract, which carries no IMD or ONSPD columns, so
`IMD_DECILE` ends up entirely NaN for the latest snapshot. `build_dashboard_cache.py` then fails in
`cluster_practices`, because `SimpleImputer(strategy="median")` silently drops an all-NaN column and
the result is rebuilt against a column index one wider than itself:

```
ValueError: Shape of passed values is (6129, 2), indices imply (6129, 3)
```

`join_enrichment.py` rewrites `data/processed/mapping.parquet` in place, re-enriching every month
including the new one. A healthy run reports 100% IMD and geo coverage.

## Setup

### 1. Clone the dedicated working copy

The task must not run against your development checkout — `local_refresh.ps1` hard-resets to
`origin/main` and would discard uncommitted work. It refuses to run against `D:\GitHub\nhs-gp-analytics`,
but keep them separate anyway.

```powershell
git clone https://github.com/jad-22/nhs-gp-analytics.git "$env:LOCALAPPDATA\nhs-gp-refresh\repo"
```

The task runs the copy of `local_refresh.ps1` inside that clone, and each run resets to `origin/main`
first — so the script keeps itself up to date. (PowerShell parses the whole file before executing,
so a reset that rewrites the script mid-run is harmless.)

### 2. Check the interpreter

The script defaults to `%USERPROFILE%\anaconda3\envs\nhs-gp\python.exe` and refuses anything below
3.11 — `pipeline/backfill.py` imports `datetime.UTC`, which does not exist on 3.9, so a task that
inherits the Anaconda base interpreter fails at import.

```powershell
& "$env:USERPROFILE\anaconda3\envs\nhs-gp\python.exe" --version   # expect 3.11.x
```

### 3. Set up push credentials

The task pushes to `main` non-interactively. Git Credential Manager can raise a GUI prompt on
expiry, which will hang a scheduled run until the task's one-hour limit, so prefer a token:

1. Create a fine-grained PAT scoped to `jad-22/nhs-gp-analytics` with **Contents: read and write**.
2. Store it so `git push` never prompts:

```powershell
cmdkey /generic:git:https://github.com /user:jad-22 /pass:<token>
```

### 4. Do a supervised first run

```powershell
cd "$env:LOCALAPPDATA\nhs-gp-refresh\repo"
powershell -ExecutionPolicy Bypass -File scripts\local_refresh.ps1 -NoPush
```

`-NoPush` runs everything including the commit, but leaves it local so you can inspect the diff
before anything reaches `main`. Drop the flag once it looks right.

### 5. Register the scheduled task

```powershell
Register-ScheduledTask -TaskName 'NHS GP Monthly Refresh' `
  -Xml (Get-Content -Raw "$env:LOCALAPPDATA\nhs-gp-refresh\repo\scripts\nhs-gp-monthly-refresh.xml")
```

The trigger is **daily**, not aimed at publication day. `local_refresh.ps1` exits immediately when
the current month is already ingested on `origin/main`, so most days cost a fetch and one request.
That is deliberate: a machine that happens to be off on publication day picks the work up on its
next run, which a once-a-month trigger cannot do.

It also sidesteps a latent bug in the old cron, `30 10 8-14 * 4`. That was meant to be "the second
Thursday", but when both day-of-month and day-of-week are restricted, cron **ORs** them — so it
actually fired on days 8–14 *and* every Thursday, roughly 11 times a month.

The task runs under `InteractiveToken`, i.e. only while you are logged on. To run regardless, change
the principal to a password logon type and supply credentials at registration.

## Operating it

Logs go to `%LOCALAPPDATA%\nhs-gp-refresh\logs\refresh-YYYY-MM.log`, one file per month.

Exit codes are what Task Scheduler shows in **Last Run Result**:

| Code | Meaning | Action |
| --- | --- | --- |
| 0 | Ingested, already up to date, or not published yet | None |
| 1 | Ingestion, cache rebuild, or push failed | Check the log |
| 2 | Precondition failed (missing/too-old interpreter, bad `-RepoPath`) | Fix setup |

`not_published` is an expected daily outcome before NHS Digital publishes, so it exits 0. This is
why the script reads `data/pipeline_log.json` rather than trusting the exit code of
`pipeline.monthly`, which returns 1 for both `failed` and `not_published`.

Useful invocations:

```powershell
# Re-ingest a specific month
.\scripts\local_refresh.ps1 -Month july -Year 2026 -Force

# Ad-hoc run against a different clone
.\scripts\local_refresh.ps1 -RepoPath D:\tmp\nhs-check -NoPush
```

## Outstanding data gap

`origin/main` has no **july 2026** — its last successful ingest is june 2026, because the July and
August CI runs both 403'd. The publication page is live, so once the task is set up:

```powershell
.\scripts\local_refresh.ps1 -Month july -Year 2026
```

Run it before the August refresh so the series stays contiguous.

## Still to do

The forecast cache rebuild (~2 hours, no network) should stay on GitHub-hosted runners, triggered by
the data push this task produces. That is not wired up yet: `scripts/build_forecast_cache.py` lives
only on the unmerged `feature/statistical-forecasters` branch. Once it lands on `main`, add a
workflow triggered on `push` to `main` with `paths: data/processed/**`. The commit message this
script writes deliberately omits `[skip ci]` so that trigger will fire.
