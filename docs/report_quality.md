# Report Quality Guide

A SIL-driven audit only matters if the resulting Bug Bounty / QA report
gets triaged, taken seriously, and fixed. This guide documents the
quality bar that makes that more likely.

The Markdown produced by `sil report generate` is a *skeleton*. Expect to
spend 15-30 minutes editing it before submitting.

## 1. A good title

**Format.** `<surface>: <bad invariant> after <transition>`

| Bad title                                  | Better title                                                              |
|--------------------------------------------|---------------------------------------------------------------------------|
| `Bug in deletion`                          | `Search index: deleted file body returned past 1h SLA`                    |
| `Connector revoke is broken`               | `Drive connector: documents indexable for 24h after revoke`               |
| `Permission downgrade leaks data`          | `Members API: owner_id leaked to downgraded viewer`                       |
| `Cache is stale`                           | `Public profile CDN: Cache-Control: 5m honored, but POP-X serves 30m+`    |

A good title makes the invariant, the surface, and the transition visible
without the body.

## 2. Reproduction steps

The triage engineer must be able to reproduce the issue in under 10
minutes. SIL helps you keep this honest:

```
1. Create scenario (sil scenario create ...).
2. Capture `before` (sil observe ...).
3. Perform the transition (UI step described as a single sentence).
4. Capture `after` immediately.
5. Run `sil diff --before <before_id> --after <after_id> --keyword <signature>`.
6. Optional: `sil schedule --in 1h` and re-observe.
```

Numbered, copy-pastable. No "and then I clicked around for a bit".

## 3. Expected vs. Actual

Two short paragraphs. Expected = the public documentation, the API
contract, or a reasonable reading of the privacy policy. Actual = what
SIL captured, with the exact persistence finding from `sil diff`.

```
Expected: per the docs at /privacy#deletion, deleted files should not
appear in retrieval results within 5 minutes.

Actual: 75 minutes after deletion, retrieval API still returned the
deleted file's body. See `Diff #2` (severity hint: needs_review).
```

## 4. Impact

**Frame the impact in terms a non-engineer can act on.**

- Who is affected? (yourself, every user, only paid users, only admins…)
- What can they observe / do? (read deleted content, escalate, etc.)
- Under what conditions? (after revoke, after downgrade, with a CDN miss…)

Avoid:

- Adding "RCE" / "privilege escalation" to make a low-impact issue look
  scary. Triage will downgrade it and trust will drop.
- Claiming GDPR / SOC2 / HIPAA implications without specifics.

## 5. Evidence

The `Evidence` section in the SIL report points reviewers at the artifact
directory. The easiest way to ship that is `sil scenario export`:

```
sil scenario export --scenario <id>
# wrote export bundle .../scenario_0001_export_<ts>.zip
#   files: 7
#   size:  18421 bytes
#   sha256: 5e7c…
```

The bundle is a single zip containing `manifest.json` (with SHA-256 of
every member), `report.md` (redacted by default), and the artifact tree.
Include in your final submission:

- That zip, transmitted via a channel the program acknowledges (signed
  upload, encrypted email, program portal — **not** public paste).
- The bundle's SHA-256 as printed by `sil scenario export`.
- The diff image (`diff_*.png`) for screenshot findings — automatically
  picked up by the exporter when it lives next to an after artifact.

Do **not** include:

- Raw cookies / Authorization headers.
- Other users' personal data, even if redacted.
- Full API key secrets — prefix only, and only if the program asks for
  proof of ownership.

If the program insists on chat / email evidence, send a *signed link* to
the artifact bundle from a service the program has acknowledged, not the
raw bytes.

## 6. Minimal data retention

- Capture only what your hypothesis needs. If you only need the search
  page, don't take a full-page screenshot of the dashboard.
- Use `--mask` on the Playwright observer to black out anything you
  didn't expect to capture.
- Use `--ignore-region` on `sil diff` to suppress dynamic regions you
  don't care about (timestamps, "you" badges).
- Run `sil report generate` with the default `--redact` on. Only turn
  `--no-redact` on inside the operator's local notes.

## 7. Masking

The default `--redact` patterns in `sil report` cover:

- Email addresses → `[REDACTED_EMAIL]`
- UUIDs → `[REDACTED_UUID]`
- PEM private-key blocks → `[REDACTED_PRIVATE_KEY]`
- JWTs (`eyJ…` three base64url segments) → `[REDACTED_JWT]`
- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`) → `[REDACTED_GITHUB_TOKEN]`
- Slack tokens (`xox[abprso]-…`) → `[REDACTED_SLACK_TOKEN]`
- Google API keys (`AIza…`, 39 chars) → `[REDACTED_GOOGLE_API_KEY]`
- AWS access key IDs (`AKIA…` / `ASIA…`) → `[REDACTED_AWS_KEY_ID]`
- `sk_*` / `pk_*` / `key_*` / `token_*` / `api_*` token-like strings
- `Bearer <opaque>` tokens
- IPv4 addresses

Artifact paths in both the Observations and Evidence sections of the
generated report go through the same redaction pass, so a sensitive
substring embedded in a filename (`alice@example.com`, `AKIA…`, etc.) is
masked in both places.

Always still review by hand. Domain-specific identifiers (`org_`, `team_`,
internal route names) are not auto-masked because they often *are* what
you are reporting on.

## 8. Severity-hint guidance

SIL emits a `severity_hint` on each diff. Translate it carefully when
filling out the program's severity form:

| SIL hint        | Meaning                                                                 | Bug Bounty severity floor        |
|-----------------|-------------------------------------------------------------------------|----------------------------------|
| `info`          | No persistence; finding is a baseline observation.                      | Don't submit.                    |
| `low`           | Minor textual / structural diff, no security boundary crossed.          | Hardening recommendation.        |
| `medium`        | Internal identifiers leak; abuse path requires more steps.              | Possibly informative; submit if you can demonstrate abuse. |
| `needs_review`  | Operator-declared keyword still present; manual confirmation required.  | Often the right level — let the triage team decide. |
| `high`          | Stack traces / many residuals; clear cross-boundary leak.               | Yes, submit; include impact narrative. |

These are **hints**, not the program's severity. Always run the program's
own severity rubric before submitting.

## 9. Examples that trend "informative"

Programs commonly mark these as informative or won't-fix:

- Audit-log entries keeping the *name* of deleted items.
- A UI link visible briefly while a server-side state change propagates.
- Static asset URLs cached by an intermediary CDN that is not the
  vendor's own.
- A response field that hasn't changed in years and the vendor has
  publicly stated is intentional.
- An "internal" id leaked in HTML markup that the vendor has decided is
  not sensitive (e.g. document slug).

If your finding fits any of the above, fold it into a bundled
"hardening recommendations" note rather than a standalone report.

## 10. Tracking findings through triage

`sil finding open --scenario <id> --title "<surface>: <invariant> after <transition>"
--severity <level> --diff <diff_id>` opens a finding bound to the diff(s)
that surfaced it. Walk it through the lifecycle:

```
open            ← initial state after `sil finding open`
submitted       ← --status submitted --external-id H1-12345
needs_more_info ← triager asked for clarification
accepted        ← program accepted; bounty pending
fixed           ← --status fixed (auto-stamps closed_at)
wont_fix        ← --status wont_fix (auto-stamps closed_at)
duplicate       ← --status duplicate (auto-stamps closed_at)
```

When the program awards a bounty, record it: `sil finding update --id <id>
--paid 50000 --currency USD` (units are the smallest currency unit;
`50000` means USD 500.00). The amount flows into the next exported bundle's
`manifest.json` and is rendered in `report.md` under that finding.

## 11. Pre-submission checklist

- [ ] Title fits `<surface>: <bad invariant> after <transition>`.
- [ ] Reproduction steps are numbered and copy-pastable.
- [ ] Expected and Actual are each one paragraph.
- [ ] Impact is concrete and proportional.
- [ ] Evidence does not contain live secrets or other users' PII.
- [ ] `--redact` was applied; you re-checked by hand.
- [ ] Severity claim matches the program's rubric, not just SIL's hint.
- [ ] You can reproduce on a freshly-created tenant or a documented setup.
- [ ] You have NOT performed any prohibited action listed in
      `docs/scenario_playbook.md`.
