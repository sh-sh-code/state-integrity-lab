# Methodology

State Integrity Lab uses a four-step observation cycle around any state
transition you want to audit. The operator drives the transition manually;
the tool records evidence, performs diffs, and produces a report.

## The cycle

```
1. before          → capture evidence of current state
2. transition      → you perform the change in the target service
3. after           → capture evidence again, immediately
4. delayed_after   → re-capture later (5m, 1h, 24h) to catch cache lag
```

Every artifact (text, JSON, HTML, screenshot, API response) is stored under
`artifacts/scenario_<id>_<slug>/<phase>/` with a UTC timestamp prefix, so the
sort order matches the time order.

## Phases

### `before`

Capture the **state you expect to disappear** after the transition. Examples:

- Search results for a keyword that should only exist while a connector is
  attached.
- A list of files that should be gone after deletion.
- An export bundle (json / csv) generated **before** the transition.
- A screenshot of an admin-only screen that the user should lose access to.

If you cannot articulate "what specifically should disappear?" in the
hypothesis, the diff later will not be meaningful. Be specific.

### `transition`

You — the human — perform the change in the target service. The tool only
**records** that you did it via `sil transition mark`. The tool never
performs the transition automatically; that boundary is intentional.

Recommended transition types are listed in `sil transition list`. You may
record any free-form type, but the tool will print suggested follow-ups for
the known ones (revoke, delete, downgrade, rotate, …).

### `after`

Capture the **same surfaces** you captured in `before`, immediately after the
transition. The matching scopes (same search query, same export format, same
URL) are what makes the diff meaningful.

### `delayed_after`

Re-capture later. Use `sil schedule --scenario <id> --in 5m --in 1h --in 24h`
to record planned re-observation times. Phase 1 only writes rows to the
`delayed_checks` table; you re-run `sil observe ...` yourself when the time
comes. Phase 2 will add an actual runner.

## Diffing

`sil diff --before <obs> --after <obs>` chooses a strategy based on the
observation types:

- `json + json` → structural JSON diff (added / removed / changed paths).
- `screenshot + screenshot` → byte / size compare (perceptual diff is Phase 2).
- everything else → unified text diff plus persistence heuristics.

### Persistence heuristics (Phase 1)

The text diff applies these rules and emits `PersistenceFinding`s:

1. **declared_keyword_persisted** — a keyword you passed via `--keyword` still
   appears in the `after` artifact.
2. **internal_identifier_visible** — UUIDs, absolute paths, `org_*`, `team_*`,
   `user_*` IDs, secret-like prefixes, or stack traces appear in `after`.
3. **line_unchanged_after_transition** — a line containing your declared
   keyword is identical in `before` and `after` (catches "UI hides but the
   underlying data is unchanged").

These are hints, not verdicts. Always review by hand before reporting.

## Report

`sil report generate --scenario <id>` writes a Markdown file under `reports/`
with the scenario header, hypothesis, scope statement, observations,
transitions, diff results, delayed checks, and a free-form notes section.
Redaction (emails, UUIDs, token-like strings, IP addresses) is on by default.

## Phase 2 backlog

These are the items deliberately deferred from Phase 1:

1. **Playwright-driven observation.** Optional, opt-in per service. Re-uses an
   existing browser profile so credentials are *yours* and never live in the
   tool. Captures HTML and screenshots in one shot, with explicit ToS / scope
   gating before any automation runs.
2. **Perceptual screenshot diff.** Pillow + ImageChops, with a configurable
   tolerance and ignore-region masks for dynamic UI elements.
3. **Delayed-check runner.** A small background process (cron, systemd, or
   APScheduler) that pulls due `delayed_checks` and re-prompts the operator —
   it does **not** observe anything itself.
4. **API observation templates.** Service-specific request shapes (the
   operator supplies their own credentials), with response normalization for
   stable diffs.
5. **Export-bundle comparison.** `sil diff --bundle before.zip after.zip` that
   walks a typical export and surfaces residual records.
6. **Severity-hint refinement.** Move from rule-based to a small
   weighted-rules model with documented rationale.
