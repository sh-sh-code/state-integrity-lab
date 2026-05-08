# Example report

This is a **fictional, illustrative** example of what
`sil report generate --scenario <id>` produces. The values are made up.

---

# State Integrity Lab Report — example-drive-revoke

- **Scenario ID**: `1`
- **Target service**: `example.com`
- **Template**: `connector_revoke_persistence`
- **Status**: `in_progress`
- **Created**: 2026-05-08 14:00:00Z
- **Generated**: 2026-05-08 15:30:00Z

## Hypothesis

After revoking the Drive connector, content sourced from Drive should
disappear from search, retrieval, history, and export across all surfaces.

## Scope & Safety Statement

- All observations were performed on the operator's own account, on test data,
  or within an explicitly authorized Bug Bounty / audit scope.
- No authentication bypass, rate-limit evasion, DoS, or third-party data
  access was attempted.
- Sensitive identifiers in this report have been redacted where the generator
  could detect them. Human review is still required before sharing.

## Observations

### Phase: `before`

- **#1** `html` at 2026-05-08 14:01:10Z
  - artifact: `artifacts/scenario_0001_example-drive-revoke/before/20260508T140110Z_search.html`
  - note: Search for `connector-only-keyword` returned 3 hits (own test docs).

### Phase: `after`

- **#2** `html` at 2026-05-08 14:03:55Z
  - artifact: `artifacts/scenario_0001_example-drive-revoke/after/20260508T140355Z_search.html`
  - note: Same search, immediately after revoke.

### Phase: `delayed_after`

- **#3** `html` at 2026-05-08 15:05:11Z
  - artifact: `artifacts/scenario_0001_example-drive-revoke/delayed_after/20260508T150511Z_search.html`
  - note: Re-ran the same search 1h after revoke.

## Transitions

- **#1** `revoked_oauth` by `human` at 2026-05-08 14:02:00Z
  - note: Revoked the Drive connector from /settings/integrations.

## Diff results

#### Diff #1 — `text` (severity hint: `needs_review`)
- before observation: `#1`, after observation: `#2`
- recorded at: 2026-05-08 14:04:30Z

```text
== Unified text diff ==
--- before
+++ after
@@
-3 results for "connector-only-keyword"
+1 result for "connector-only-keyword"

== Persistence findings ==
[needs_review] declared_keyword_persisted: keyword='connector-only-keyword' - Operator-declared keyword still present in `after`. Confirm whether this surface should have been purged.
[medium] internal_identifier_visible: keyword='[REDACTED_UUID]' - Looks like internal uuid surfaced post-transition.
```

## Delayed checks

- **#1** run_after=2026-05-08 14:08:00Z status=executed
  - note: re-observe after 5m
- **#2** run_after=2026-05-08 15:03:00Z status=executed
  - note: re-observe after 1h
- **#3** run_after=2026-05-09 14:03:00Z status=pending
  - note: re-observe after 24h

## Operator notes

After 1h, search still returned 1 hit pointing at a Drive document. Manual
inspection confirmed the title and snippet were derived from the connector
data even though the connector had been revoked. Reported via the program's
intake form on 2026-05-08, reference `BB-XXXX`.
