# Local Monthly Refresh

The monthly ingestion runs from a scheduled task on a local machine rather than from GitHub
Actions. This document covers why, and how to set it up.

For driving a refresh manually — including the abort gates and commit message format used when an
agent runs it on request — see [`RUNBOOK_MONTHLY_REFRESH.md`](RUNBOOK_MONTHLY_REFRESH.md).

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

## Verification record (2026-08-28)

The task is registered and armed. First scheduled fire is 2026-09-01 10:30.

Verified by a manual `-Month august -Year 2026 -Force -NoPush` run:

| Step | Result |
| --- | --- |
| Scrape `digital.nhs.uk` | 200 from a residential IP; resolved `/45/E255E0/` and `/26/656B2E/` |
| `pipeline.monthly` | exit 0, 6,129 practices |
| `join_enrichment.py` | 514,047 rows, IMD 100%, geo 100% |
| `build_dashboard_cache.py` | 8 parquet outputs |
| Commit | `data: monthly pipeline refresh (august 2026)` |
| Wall clock | ~1m45s, well inside the 1h `ExecutionTimeLimit` |

Re-ingesting an already-ingested month changed **only** `data/pipeline_log.json` — every file under
`data/processed/` came out byte-identical. The pipeline is deterministic, so a `-Force` re-run cannot
corrupt committed data.

Verified separately by an on-demand run of the registered task, which exercises the parts the manual
run does not: `%LOCALAPPDATA%` expansion inside the task's `Arguments`, interpreter resolution
without an activated conda env, `-NoProfile -NonInteractive` execution, log writing, and git under
the task's own token. It reset the clone, hit the already-ingested guard, and exited 0 in about a
second — `LastTaskResult: 0`. The reset also discarded the manual run's local commit, confirming the
clone is self-cleaning and needs no manual tidying between runs.

### Not yet verified

**`git push` has never run from the task's non-interactive context.** Both verification runs used
`-NoPush`, and the on-demand run exited at the guard before reaching the push. This is the one step
the doc's own setup notes flag as risky: if Credential Manager decides to prompt under a
non-interactive token, there is no UI to answer it and the run will hang until the one-hour
`ExecutionTimeLimit` kills it. The stored `cmdkey` entry for `jad-22` is intended to prevent that,
but it is unproven. The september 2026 publication is the first run that will actually push — check
`LastTaskResult` and the log after it.

The full ingest path has also not run under the task token; it has only been run interactively.

### Principal

The task is registered `LogonType: Interactive`, `RunLevel: Limited`, as `jason` — so it runs **only
while you are logged on**. A machine left at the login screen will not refresh. `StartWhenAvailable`
means it catches up on the next logon rather than skipping the month, so this degrades the latency
of a refresh, not its correctness. To make it fully unattended, re-register the principal with a
password logon type.

## Data gap — closed (2026-08-28)

The July and August 2026 CI runs both 403'd, leaving `origin/main` with june 2026 as its last
successful ingest. Both months have since been ingested manually and pushed: `data/pipeline_log.json`
on `origin/main` now records **july 2026** and **august 2026** as `success`, so the series is
contiguous and no backfill is outstanding.

One consequence for setting the task up: a plain `local_refresh.ps1 -NoPush` will now hit the
already-ingested guard and exit 0 in about a second without touching the network. That exercises the
guard, not the pipeline. To smoke-test the real path, force a month that is already done and hold
the push back:

```powershell
.\scripts\local_refresh.ps1 -Month august -Year 2026 -Force -NoPush
```

Inspect `git log -1 -p`, then `git reset --hard origin/main` to discard the local commit.

## Still to do

The forecast cache rebuild (~2 hours, no network) should stay on GitHub-hosted runners, triggered by
the data push this task produces. `scripts/build_forecast_cache.py` has since landed on `main`, so
the blocker is gone — what is still missing is the workflow itself: add one triggered on `push` to
`main` with `paths: data/processed/**`. The commit message this script writes
(`data: monthly pipeline refresh (<month> <year>)`) deliberately omits `[skip ci]` so that trigger
will fire.

Note the ordering when wiring it up. `api_image.yml` already triggers on `push` to `main` for
`data/processed/list_size.parquet` and `mapping.parquet`, both of which this task's commit touches —
so the API image rebuilds immediately, against forecasts that are still the previous month's, and
would rebuild again once the forecast cache is refreshed. Either chain the forecast rebuild ahead of
the image build or accept the double build.
