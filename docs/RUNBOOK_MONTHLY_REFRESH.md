# Runbook — Agent-Driven Monthly Refresh

Instructions for an AI agent asked to run the monthly NHS GP data refresh and push the result to
`main`. Follow this top to bottom. Do not improvise around the abort gates in step 4.

Background on *why* the refresh runs locally at all is in [`LOCAL_REFRESH.md`](LOCAL_REFRESH.md);
this file is only the operating procedure.

## Scope of authority

Running this runbook carries standing approval to **commit and push to `main`** — but only when
every gate in step 4 passes. Any gate failure means stop and report, not push anyway.

Three things are outside that approval and always need asking first:

- Using `-Force` to re-ingest a month already recorded as `success`.
- Pushing a commit whose only change is `data/pipeline_log.json` (see step 4e).
- Anything touching `git push --force`, history rewriting, or branches other than `main`.

## 0. Where this runs

| | |
| --- | --- |
| Working clone | `%LOCALAPPDATA%\nhs-gp-refresh\repo` |
| Never run in | `D:\GitHub\nhs-gp-analytics` — the dev checkout |
| Interpreter | `%USERPROFILE%\anaconda3\envs\nhs-gp\python.exe` (3.11+) |
| Log | `%LOCALAPPDATA%\nhs-gp-refresh\logs\refresh-YYYY-MM.log` |

The script hard-resets to `origin/main` on every run and would discard uncommitted work, so the dev
checkout is not a valid target. It refuses `D:\GitHub\nhs-gp-analytics` outright, but do not rely on
that guard — pass no `-RepoPath` and let the default apply.

Any uncommitted work you have in the dev checkout is unaffected by all of this. The two clones are
independent.

## 1. Preflight

```powershell
# a. The scheduled task must not be mid-run — both would fight over the same clone.
(Get-ScheduledTask -TaskName 'NHS GP Monthly Refresh').State

# b. Clone present and clean.
git -C "$env:LOCALAPPDATA\nhs-gp-refresh\repo" status -sb
```

If the task state is `Running`, wait for it to finish and start over. If the clone is missing, see
"Setup" in `LOCAL_REFRESH.md` — do not silently re-clone into a different path.

A dirty clone is not a problem; the script resets it. A clone sitting *ahead* of `origin/main` means
a previous run committed without pushing — read that commit before discarding it.

## 2. Run the pipeline

Always with `-NoPush`. The script's own commit message is deliberately minimal, and you are going to
replace it in step 5 before anything reaches `main`.

```powershell
cd "$env:LOCALAPPDATA\nhs-gp-refresh\repo"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_refresh.ps1 -NoPush
```

Omit `-Month`/`-Year` for the current month. Supply both to target a specific one.

Takes roughly two minutes. Run it in the background and wait rather than polling.

## 3. Classify the outcome

Read the last lines of the log. The script ends with exactly one `=== Finished: … ===` marker, and
that marker — not the exit code — tells you what happened. Exit code `0` covers three different
benign outcomes.

| Marker | Exit | Meaning | Do |
| --- | --- | --- | --- |
| `Finished: committed, not pushed` | 0 | New data committed locally | Go to step 4 |
| `Finished: already up to date` | 0 | Month already `success` on `origin/main` | Stop. Report. Ask before `-Force` |
| `Finished: not published` | 0 | NHS has not published yet | Stop. Report. Expected before publication day |
| `Finished: no changes` | 0 | Ran clean but produced no diff | Stop. Report — unusual, worth a look |
| *(none)* | 1 | Ingest, cache rebuild, or push failed | Stop. Report the log tail |
| *(none)* | 2 | Precondition failed (interpreter, bad path) | Stop. Fix setup, do not retry blindly |

Only `committed, not pushed` proceeds. For everything else, report plainly and stop — a month that
is not published yet is a normal outcome, not a failure to work around.

## 4. Abort gates

All five must pass. If any fails, **do not push.** Report what failed and leave the commit local —
it is harmless there, and the next run resets it away.

**a. Status is `success`.** Read the newest record for the target month in
`data/pipeline_log.json` and confirm `status == "success"` and `error == null`.

**b. Coverage is 100%.** The `join_enrichment.py` output must report IMD coverage and geo coverage
both at `100.0%`. Anything less means the enrichment join has holes and `build_dashboard_cache.py`
may have silently produced degraded clusters.

**c. Practice count is plausible.** Compare `practices_ingested` against the previous successful
month. The real series drifts down slowly through practice mergers — recent months moved by 1–14
practices, well under 0.5%. Treat a swing beyond **±2%** as a parse failure until proven otherwise
and stop.

**d. Only expected files changed.**

```powershell
git -C "$env:LOCALAPPDATA\nhs-gp-refresh\repo" diff --stat origin/main HEAD
```

Everything must sit under `data/processed/` or be `data/pipeline_log.json`. Any source file in the
diff means something is wrong — stop.

**e. The diff is not log-only.** If `data/pipeline_log.json` is the *only* changed file, the
pipeline re-ingested a month whose processed output was byte-identical. That is the expected result
of a `-Force` re-run and is normally not worth a commit on `main`. Ask before pushing it.

## 5. Rewrite the commit message and push

The script has already committed with a bare subject. Amend it — the commit has never been pushed,
so this is safe and is the only way to attach the stats.

```powershell
cd "$env:LOCALAPPDATA\nhs-gp-refresh\repo"
git commit --amend -m "<message below>"
git push origin main
```

### Commit message format

Subject line stays exactly as the script writes it, so scheduled and agent-driven refreshes sort
together in the log:

```
data: monthly pipeline refresh (<month> <year>)

Practices ingested : <n> (<+/-d> vs <previous month>, <+/-p>%)
Mapping rows       : <n>
IMD coverage       : <p>%
Geo coverage       : <p>%

Dashboard cache rebuilt (<k> outputs):
  latest_snapshot      <rows> x <cols>
  list_size_geo        <rows> x <cols>
  market_share         <rows> x <cols>
  migrations           <rows> x <cols>
  deprivation_latest   <rows> x <cols>
  cluster_k            <rows> x <cols>
  inequality           <rows> x <cols>
  correlations         <rows> x <cols>

Source:
  totals  <totals_url>
  mapping <mapping_url>

Run: local_refresh.ps1, <duration>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

Every number comes from the run you just did — the log tail for coverage and cache dimensions, the
`pipeline_log.json` record for counts and URLs. Do not carry figures over from a previous run or
from this document's examples. If a value is genuinely unavailable, write `unknown` rather than
guessing.

The two source URLs matter more than they look: they carry the opaque per-file hex segment that
changes every month, so recording them is the only durable evidence of which published files a given
commit was actually built from.

Add the session trailer beneath `Co-Authored-By` if one is available for the session.

## 6. Report

State plainly:

- Month ingested, practice count, and the delta against the previous month.
- Coverage figures.
- The pushed commit SHA.
- Anything that looked off but passed the gates.

Then note the two automatic consequences of the push, so they are never a surprise:

- **`api_image.yml` rebuilds the API image.** It triggers on `push` to `main` for
  `data/processed/list_size.parquet` and `mapping.parquet`, both of which this commit touches. It
  will build against the *previous* month's forecasts, because the forecast cache is rebuilt
  separately and is not wired up yet.
- **Streamlit Cloud redeploys** `https://nhs-gp-analytics.streamlit.app` from `main`.

Neither needs action. Both are worth mentioning.

## Notes

**Why `-NoPush` then amend, rather than letting the script push.** The script has to work unattended
under Task Scheduler, where nothing can compose a rich message, so its own commit message is
deliberately minimal. Running it with `-NoPush` and amending keeps one code path for both callers
while still getting the stats onto agent-driven commits. It also puts the abort gates *before* the
push instead of after it.

**Two commit message styles on `main` is intended.** A bare `data: monthly pipeline refresh (…)` is
the scheduled task; one carrying a stats block is an agent-driven run. That distinction is useful
when reading the history — do not normalise it away.

**No `[skip ci]`.** The subject deliberately omits it, because the push is what a future
forecast-cache workflow will trigger on. Do not add it.
