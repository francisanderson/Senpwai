# Senpwai maintenance backlog

Snapshot: 2026-09-17. Tracker: https://github.com/francisanderson/Senpwai/issues

Curated from 36 open upstream reports, not a verbatim issue migration. Original authors, comments and attachments remain upstream. Similar symptoms are not confirmed duplicate root causes. No application fixes have been applied or verified yet.

## Top five

1. **P1: Missing size metadata crash (#108 upstream).** First small fix candidate: reproduce `calculate_total_download_size` receiving a label without an integer MB match, define unknown-size behavior and add offline tests. Preserve correct valid totals; never present a partial sum as the complete total.
2. **P1: Provider domains/search (#120, #99, #88, #91).** Validate current domains from authoritative evidence before changing constants. Upstream PRs #124 and #121 both propose `.pw`, but this is not independent validation. #121 includes unrelated lockfile churn. Verify search independently of downloads.
3. **P1: Resource length and invalid responses (#118, #117, #116, #84).** Use local HTTP fixtures to distinguish absent size, error HTML and interrupted media. Surface useful failures and avoid saving error pages as completed media.
4. **P1: Hangs and cancellation (#126, #125, #123, #119, #113, #107, #102, #98, #71, #90).** Collect version, OS, provider and failing stage; split confirmed root causes into small fixes. Bound retries and keep UI controls usable after failure.
5. **P1: Offline maintenance baseline.** Current Poe tests depend on live providers and downloads. Add isolated regression checks with each fix; document Python 3.11 setup and lint/build baseline before dependency upgrades.

Numbers above refer to https://github.com/SenZmaKi/Senpwai/issues/NUMBER.

## Remaining coverage

| Area | Upstream reports | Initial disposition |
|---|---|---|
| Unexpected episode/link responses | #103, #104, #114 | P1: offline malformed-response cases; split link parsing from zero-episode handling |
| Provider verification block | #122 | P1: clear blocked-response error, no verification bypass |
| Episode identity | #82, #57 | P2: fractional/combined numbering regression cases |
| Search sound controls | #109, #101 | P2: inspect existing settings, make silence persistent/discoverable |
| Desktop startup | #92 | P2: needs textual traceback and environment details |
| Termux installation | #68 | P2: review upstream PR #87; verify in Termux before claiming support |
| Nix/dependencies | #83 | P2: review upstream PR #93 separately from application fixes |
| More sources | #110, #97, #78 | P3: feasibility decision, not implementation commitment |
| Native Android | #94 | P3: scope decision; upstream is working on a Flutter rewrite |
| Season/media-library naming | #80 | P3: opt-in naming specification before changing existing layouts |
| Download-all/recovery | #86 | P3: clarify retry-missing need; no site-wide download feature planned |

## Maintenance rules

- GitHub Issues is the task source of truth; this file is the initial triage snapshot.
- Retain GPL licensing and upstream attribution. Do not alter upstream issues.
- Use one focused branch/change at a time, a failing regression test first, and review before merging.
- Do not mix dependency refreshes, provider patches and UI changes in a single fix.
- Unknown sizes and unavailable providers must be explicit, not silent zero/partial success.
- Live-provider health, packaging and GUI checks must be reported separately from offline unit checks.
- No CAPTCHA solving, cookie harvesting or access-control bypass work.

First-fix preparation and checkpoints: [tasks/plan.md](tasks/plan.md).
