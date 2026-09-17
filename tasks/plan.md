# First-fix maintenance plan: pahe size metadata guard

## Status
Implemented on branch `fix/pahe-size-metadata`, commit `67b8c19`. Not merged, not pushed. This document is the checkpoint record; [BACKLOG.md](../BACKLOG.md) stays the triage snapshot.

## Overview
Upstream #108 shows `calculate_total_download_size` crashing with `AttributeError: 'NoneType' object has no attribute 'group'` when an episode label has no integer-MB text. The production fix raises an explicit `ValueError("missing size metadata")` instead. This makes the failure diagnosable; it does not yet change how the GUI or CLI recover from that error.

## Baseline decisions
- Production code changes: `Senpwai/senpwai/scrapers/pahe/main.py` only (3 lines, no constants or callers touched).
- Regression test: `Senpwai/tests/test_pahe_size.py`, stdlib `unittest` only. It compiles the real production function and regex via `ast` because a normal import reaches legacy installer-deletion side effects in `senpwai/common/static.py`.
- Environment: Python 3.11 via `py -V:Astral/CPython3.11.15` (project pins 3.11). The Store `python` is 3.13 and lacks `yarl`.
- `.gitignore`: changed `tests/` to `tests/*` with `!tests/test_pahe_size.py` so the regression test is versioned while other local test scratch stays ignored.
- Lint: `ruff` is not installed in this environment; `scripts/ruff.py` auto-commits, so `poe format`/`lint_fix` are not used. Lint baseline is unverified, recorded in fork issue #5.
- No dependency refreshes, provider/domain changes, or GUI changes were mixed into this fix.

## Test evidence
- RED: with the fix stashed, the test reproduces the reported crash (`AttributeError: 'NoneType' object has no attribute 'group'`, 2 errors, FAILED) on Python 3.11.
- GREEN: with the fix applied, both tests pass (`Ran 2 tests ... OK`, 0.001s).
- Live provider tests (`poe test*`, `senpwai.scrapers.test`) were not run: they hit external sites.

## Tasks
- [x] Task 1: Guard unmatched size regex with explicit ValueError (`main.py:283`).
- [x] Task 2: Offline regression test, RED-then-GREEN on Python 3.11.
- [x] Task 3: Keep the test versioned via a narrow `.gitignore` allowlist.
- [ ] Task 4: Update fork issue #1 with implementation and test evidence after push.
- [ ] Task 5: Merge the branch after human review of the diff.

## Checkpoint (before merge)
- [x] Offline regression suite passes.
- [x] RED state proven against unfixed code.
- [x] Working tree clean except `BACKLOG.md` (planned next commit) and `tasks/plan.md`.
- [ ] GUI and CLI run against a real provider to observe the error path end to end (not possible offline; record explicitly in the issue).
- [ ] Human review and approval of the commit before merging.

## Follow-ups (tracked in fork issues)
- #1 unknown-size behavior in CLI/GUI; this fix only replaces the raw crash.
- #6 similar missing-regex guards for #103/#104 link parsing.
- #5 offline test baseline, lint and dependency constraints.
