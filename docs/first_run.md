# First Run — annotated end-to-end walkthrough

This guide walks through SIL on a single scenario, end to end, with the
exact commands and the exact outputs you should expect. Use it as the
template for your first real Bug Bounty / QA engagement.

Everything below was produced by running the actual CLI against a
synthetic fixture; nothing is mocked.

> **Before you start.** Re-read `docs/scenario_playbook.md` for the
> "Prohibited actions" applicable to the template you plan to use, and
> the pre-flight checklist in the top-level `README.md`. SIL only
> works correctly when pointed at services you have authorization to
> test on your own account or sandbox tenant.

---

## 0. Install + configure

```bash
pip install -e .[dev]

export SIL_DB_PATH=$PWD/db.sqlite3
export SIL_ARTIFACTS_DIR=$PWD/artifacts
export SIL_REPORTS_DIR=$PWD/reports
export SIL_REDACT_BY_DEFAULT=true
```

`SIL_REDACT_BY_DEFAULT=true` means every report and exported bundle
masks email / UUID / JWT / GitHub PAT / AWS / Slack / Google API key
patterns by default. You can still pass `--no-redact` per command for
local notes.

---

## 1. Bootstrap the scenario with the wizard

```bash
sil init --wizard
```

The wizard asks six questions. Sample answers for an "export after
deletion" scenario against your own account on `acme.example`:

```
1. Pick a scenario template:
  1. connector_revoke_persistence
  2. project_knowledge_deletion
  3. team_permission_downgrade
  4. api_key_rotation_persistence
  5. export_after_deletion        ← pick this
  6. delayed_cache_inconsistency
Enter number (1-6) or key [1]: 5

2. Target service: acme.example
3. Where is your authorization documented?: https://hackerone.com/acme
4. Scenario short-name [acme.example-export_after_deletion-bdfd]: <Enter>
5. Generate a unique probe signature you can plant in test data? [Y/n]: y
6. Schedule delayed re-observations at 5m / 1h / 24h? [Y/n]: y
```

Output ends with:

```
Scenario created.
  id: 1  name: acme.example-export_after_deletion-bdfd
  template: export_after_deletion

Probe signature: SIL-PROBE-4e9024c5
  Plant this string in your test data BEFORE capturing the `before` phase.

Scheduled delayed checks: ids=[1, 2, 3] (5m / 1h / 24h)

Next commands:
  sil scenario show-template export_after_deletion
  sil observe html --scenario 1 --phase before --file ./snapshot.html
  ...
```

The probe signature (`SIL-PROBE-4e9024c5`) is what you will plant in
your test data and pass to `sil diff --keyword` later.

---

## 2. Plant the probe in real test data, then capture `before`

On `acme.example`, you (the operator):

1. Create a document called `SIL-PROBE-4e9024c5-roadmap`.
2. Share it with your second test account so the doc id shows up in
   the sharing API.
3. Open the export-bundle endpoint / page and download the resulting
   JSON. Save as `before_export.json` locally.

Then:

```bash
sil observe json --scenario 1 --phase before \
  --file ./before_export.json --note "graph API list pre-delete"
```

Output:

```
recorded json observation id=1
  artifact: .../scenario_0001_acme.example-..._/before/<ts>_payload.json
```

---

## 3. Perform the state transition and record it

Now manually delete the document on `acme.example`. **You do this in
the browser / API — SIL never performs the deletion for you.**

Then mark the transition:

```bash
sil transition mark --scenario 1 --type deleted_file \
  --note "deleted via dashboard at 2026-05-12T07:54Z"
```

---

## 4. Capture `after`

Re-export from `acme.example` (same query, same options as before),
save as `after_export.json`, and:

```bash
sil observe json --scenario 1 --phase after \
  --file ./after_export.json --note "graph API list post-delete"
```

---

## 5. Diff with the probe signature

```bash
sil diff --before 1 --after 2 --keyword SIL-PROBE-4e9024c5
```

Output (truncated):

```
== Structural JSON diff ==
- documents[1]: {"id": "doc_to_delete", "name": "SIL-PROBE-4e9024c5-roadmap"}
+ shared_with: [{"user": "alice", "pinned": ["doc_keep_1", "SIL-PROBE-4e9024c5-roadmap"]}]

== Persistence findings ==
 declared_keyword_persisted: keyword='SIL-PROBE-4e9024c5' - Operator-declared
 keyword still present in `after`. Confirm whether this surface should have
 been purged.

weighted score = 5.00 -> severity hint = needs_review

saved diff id=1 severity=needs_review
```

This is the moment a real bug surfaced: the document body is gone from
`documents[]` but the *id* survives in `shared_with[0].pinned[]`.
Severity hint `needs_review` means SIL wants your human judgement.

---

## 6. Annotate the scenario for the report

```bash
sil scenario annotate --scenario 1 \
  --actual "Deleted document name still appears in shared_with[0].pinned[] after deletion." \
  --impact "Other org members can see (and link to) the name of a deleted document via the sharing API." \
  --limitations "Tested only against my own org on free tier; did not verify enterprise tier." \
  --fix "Cascade-delete deleted doc IDs from shared_with[].pinned[] arrays on delete."
```

`--scope`, `--test-data`, `--expected` were already pre-filled by the
wizard. You can override any of them with another `sil scenario
annotate` call.

---

## 7. Open a finding linked to the diff

```bash
sil finding open --scenario 1 \
  --title "Deleted doc id leaks via shared_with.pinned[] after deletion" \
  --severity high \
  --diff 1 \
  --description "Probe signature SIL-PROBE-4e9024c5 persists in the after JSON under shared_with[0].pinned[1]. Reproducible on a fresh free-tier org."
```

Output: `opened finding id=1 severity=high`.

---

## 8. Generate the Markdown report and pack the export bundle

```bash
sil report generate --scenario 1
# wrote report .../scenario_0001_..._<ts>.md

sil scenario export --scenario 1 --output ./bundle.zip
# wrote export bundle ./bundle.zip
#   files: 4
#   size:  4057 bytes
#   sha256: 5837a9e943389a6b755eab07ff941ace0a8ad39eec378b95e0b7d9d5d1e892ec
```

Bundle contents:

```
manifest.json
report.md
artifacts/before/<ts>_payload.json
artifacts/after/<ts>_payload.json
```

The `manifest.json` carries SHA-256 of every member, every DB row, and
the finding row (including its `external_id` and bounty fields once you
fill them in).

---

## 9. Submit to the program and walk the lifecycle

Submit the bundle via the program's portal. As the program responds,
keep the finding state up to date locally:

```bash
sil finding update --id 1 --status submitted --external-id H1-99999
# ... wait for triage ...
sil finding update --id 1 --status accepted
# ... wait for fix verification ...
sil finding update --id 1 --status fixed --paid 25000 --currency USD
```

`--paid 25000 --currency USD` records a USD $250.00 bounty. The amount
flows into the next exported bundle's `manifest.json` and renders in
`report.md` under that finding. Re-run `sil scenario export` after each
material update so you have an audit trail.

---

## 10. Re-observe at 5m / 1h / 24h

The wizard scheduled three delayed checks. A cron entry like:

```cron
*/5 * * * * cd /path/to/state-integrity-lab && \
  /path/to/.venv/bin/sil scheduler run-due >> ~/.sil-runner.log 2>&1
```

…will print the operator prescription whenever a check becomes due:

```
# delayed re-observation due for scenario 1 (acme.example-...)
# scheduled at: 2026-05-12T08:00:25+00:00
# note: wizard-scheduled 5m re-observation

1. Re-capture the SAME surfaces you captured in the `after` phase.
   sil observe json --scenario 1 --phase delayed_after --file ./payload.json
   ...
2. Diff against the `after` observation, NOT the `before` observation.
   sil diff --before <after_obs_id> --after <delayed_obs_id> --keyword <kw>
3. When done, mark this check executed:
   sil scheduler mark-done --check 1
```

If a delayed re-pull still shows the probe signature past the
documented SLA, that strengthens the finding's severity.

---

## What you should have at this point

- A `Scenario` row in the local DB.
- Two `Observation` rows (`before` / `after`) with artifacts on disk.
- A `Transition` row recording the human-driven state change.
- A `DiffResult` row with `severity_hint=needs_review`.
- A `Finding` row walking the lifecycle (`open → submitted → accepted
  → fixed`), eventually with a recorded bounty.
- Three `DelayedCheck` rows (5m / 1h / 24h) for cache re-observation.
- A redacted `report.md` and a sealed `bundle.zip` you can hand to the
  program.

That's the full SIL loop. Repeat from §1 for the next scenario; the
artifact directory and DB stay around so you can always re-export an
older finding if the program asks for fresh evidence.
