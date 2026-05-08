# Methodology

State Integrity Lab uses a six-step observation cycle around any state
transition you want to audit. The operator drives the transition manually;
the tool records evidence, performs diffs, and produces a report.

## The standard cycle

```
1. before          → capture evidence of the pre-transition state
2. transition      → you perform the change in the target service
3. after           → capture evidence immediately after (within seconds)
4. delayed_5min    → re-capture at 5 minutes for fast caches / index lag
5. delayed_1h      → re-capture at 1 hour for medium caches / search reindex
6. delayed_24h     → re-capture at 24 hours for daily exports / long-tail caches
```

`delayed_5min`, `delayed_1h`, and `delayed_24h` all share the same database
phase (`delayed_after`); the schedule rows in `delayed_checks` distinguish
them by their `run_after` time. Use the `note` on each schedule row to tag
which delay you intend (for example `--note "5m"`).

Every artifact (text, JSON, HTML, screenshot, API response) is stored under
`artifacts/scenario_<id>_<slug>/<phase>/` with a UTC timestamp prefix, so the
sort order matches the time order.

## What to capture at each step

| Step           | Capture                                                                        | Skip                                              |
|----------------|--------------------------------------------------------------------------------|---------------------------------------------------|
| before         | List endpoints, search results, the doc body, the export bundle, screenshots. | Anything that contains *other users'* data.       |
| transition     | A short note (`sil transition mark --note "..."`) describing what you did.    | Screenshots of secret-entry dialogs.              |
| after          | The same surfaces as `before`, with the same selectors / queries.             | New surfaces that weren't in `before` — they will not produce a useful diff. |
| delayed_5min   | The surfaces most likely to be served by the front-line cache (HTML, search). | Heavy export bundles (request budget).            |
| delayed_1h     | Search index, retrieval API, exports.                                         | UI screenshots if the layout has changed by design. |
| delayed_24h    | The fullest export bundle and any audit-log endpoints with daily flush.       | Anything you have already concluded on.           |

## What NOT to keep

These belong in `.gitignore` and should never reach a Bug Bounty submission:

- Live secrets (cookies, bearer tokens, OAuth refresh tokens, full API keys).
- Other users' personal data, even if briefly visible during a session.
- Full-page screenshots of pages that contain billing details or names of
  customers you do not have permission to disclose.
- Server hostnames or internal infrastructure URLs that the program does not
  list as in-scope (an SSRF / DNS-rebind window can be reportable, but the
  evidence trail itself shouldn't broaden the attack surface for others).

When in doubt, drop the artifact and re-capture with the offending element
masked (`--mask` for the Playwright observer, manual editing otherwise).

## Reportable vs. weak findings

Use this rubric **before** drafting a Bug Bounty / QA report:

| Strong (reportable)                                                  | Weak (informative at best)                          |
|----------------------------------------------------------------------|-----------------------------------------------------|
| Deleted item's *body* persists past the documented SLA.              | Deleted item's *name* appears in the audit log (often by design). |
| Permission downgrade still allows the API to return admin-only IDs.  | A UI link is hidden but the underlying API is unchanged. |
| Rotated key still works against the production API.                  | Rotated key prefix appears in audit log entries.    |
| Export bundle's signed manifest disagrees with a member file inside. | Export bundle has a different timestamp metadata field. |
| Cross-region inconsistency past the documented cache SLA.            | One CDN POP is briefly behind another within the SLA window. |
| A finding you can reproduce on an isolated, freshly-created tenant.  | A finding that depends on a long-lived account whose state you can't fully describe. |

If your finding falls only on the right column, fold it into a single
"hardening recommendations" note rather than a standalone report.

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
- `screenshot + screenshot` → perceptual diff (Pillow + ImageChops); reports
  the differing-pixel ratio and writes a diff image. Severity is derived
  from the ratio (see table below).
- everything else → unified text diff plus persistence heuristics.

`sil bundle diff --before before.zip --after after.zip` is also available
for export bundles (zip / tar / tar.gz). Each bundle member is compared
with the strategy that fits its extension (json/text/byte) and the
keyword-persistence rule is applied to AFTER members.

### Persistence heuristics

The text diff applies these rules and emits `PersistenceFinding`s:

| Rule                                | Severity (default) | Weight |
|-------------------------------------|--------------------|--------|
| `declared_keyword_persisted`        | needs_review       | 5.0    |
| `internal_identifier_visible` (UUID, abs path, org/team/user id, secret) | medium | 2.0 |
| `internal_identifier_visible` (stack_trace)                              | high   | 6.0 |
| `line_unchanged_after_transition`   | low                | 1.0    |

`weighted_severity()` sums the weights and promotes the result:

| Total weight   | Resulting severity  |
|----------------|---------------------|
| 0              | info                |
| ≥ 1            | low                 |
| ≥ 3 (or any medium finding)        | medium    |
| ≥ 6 (or any needs_review finding)  | needs_review |
| ≥ 12 (or any high finding)         | high      |

For the perceptual screenshot diff:

| Differing-pixel ratio | Severity      |
|-----------------------|---------------|
| 0                     | info          |
| < 0.05%               | info          |
| < 1%                  | low           |
| < 5%                  | medium        |
| < 20%                 | needs_review  |
| ≥ 20%                 | high          |

These are **hints**, not verdicts. Always review by hand before reporting.

## Report

`sil report generate --scenario <id>` writes a Markdown file under `reports/`
with the scenario header, hypothesis, scope statement, observations,
transitions, diff results, delayed checks, and a free-form notes section.
Redaction (emails, UUIDs, token-like strings, IP addresses) is on by default.

## Phase 2 — implemented

All Phase 2 items below now ship in the package:

1. **Playwright-driven observation** (`sil observe playwright`). Re-uses an
   operator-supplied `storage_state.json`. SIL never logs in.
2. **Perceptual screenshot diff** (Pillow + ImageChops) with
   `--ignore-region` masks. Differing-pixel ratio drives severity.
3. **Delayed-check runner** (`sil scheduler run-due` / `sil scheduler
   mark-done`). Prints prescriptions for the operator; does not observe.
4. **API observation templates** (`sil observe api-template`) with
   `allowed_endpoints`, env-var-only tokens, mandatory `--max-requests`,
   and a minimum inter-request delay floor.
5. **Bundle diff** (`sil bundle diff`) for zip / tar / tar.gz exports with
   per-member text/JSON/byte comparison and keyword persistence.
6. **Weighted severity hint** (see the tables above).

## Phase 3+ backlog

- **Multi-region / multi-cache replay helpers** — re-observe through
  multiple egress points the operator already controls (e.g. their own VPN,
  their own region-pinned proxies) to surface CDN propagation issues.
- **i18n-aware UI snapshot normalization** — strip locale-dependent
  formatting before diffing.
- **Service-specific API templates** — gated behind explicit
  `--scope-confirmed` and the operator's own bearer token; never bundled
  with credentials.
- **Pluggable observers** — entry-point based, so new observation types can
  ship in a separate package without modifying SIL.
