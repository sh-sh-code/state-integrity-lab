# Target — Anthropic Bug Bounty (HackerOne)

A SIL-shaped scoping document for the **public** Anthropic security bug
bounty on HackerOne. Use this as a planning sheet **before** you touch
any Anthropic surface.

> **This document is a planning aid, not a green light.** Before any
> capture, read the program's policy yourself at
> <https://hackerone.com/anthropic>. The authoritative scope is whatever
> that page says today; if anything here contradicts the live policy,
> the live policy wins. The model-safety / jailbreak track is a
> **separate** program — do not mix tracks.

## What I know about the program (public sources, May 2026)

- Public on HackerOne since **2026-05-08**.
- Reward structure is **CVSS-based**, with reported amounts up to
  ~$10,000 per finding depending on severity.
- Broad asset scope based on public reporting: `claude.ai`, the
  Anthropic API, **Claude Code**, official desktop and mobile clients,
  internal infrastructure, SDKs, **Anthropic-developed MCP integrations**,
  and Chrome extensions.
- The model-safety bug bounty is a **distinct** track (jailbreaks,
  unsafe completions, prompt injection of the model itself); the
  security program covers traditional vulnerability classes — auth
  bypass, IDOR, state-integrity, leakage, etc.

## Why this is a strong first-run target for SIL

- The program is **fresh** (~1 week public). Duplicate density on
  SIL-shaped findings (residue after revoke / delete / downgrade)
  should be low compared with decade-old programs.
- **MCP integrations** are a brand-new surface that fits SIL's
  connector-revoke template essentially perfectly.
- claude.ai has rich state per user (Projects, conversations, files,
  memory, Workspace) — every one of SIL's 6 templates has a candidate
  surface here.
- Free tier exists; you can run this with a single account you own at
  no out-of-pocket cost.

## Before you start — operator pre-flight

- [ ] Read the policy at <https://hackerone.com/anthropic> end to end.
- [ ] Confirm the asset you intend to probe (e.g. `claude.ai`) is in
      the *in-scope assets* list **today**.
- [ ] Confirm the **safe harbor** clause and the **out-of-scope
      classes** (typically: physical attacks, social engineering,
      model-safety / jailbreaks, DoS / volumetric, third-party assets
      Anthropic does not own, etc.).
- [ ] Register a free account on `claude.ai`. Use it only for this
      test. Do not test against your day-job account.
- [ ] Mint a separate API key in `console.anthropic.com` for the test
      run. Store it ONLY in `SIL_*_TOKEN` env vars; never paste it
      into a SIL artifact.
- [ ] Plant a unique probe string in any test data (`SIL-PROBE-<rand>`
      from `sil init --wizard`).
- [ ] Set `SIL_REDACT_BY_DEFAULT=true` so emails / UUIDs / JWT / token
      prefixes get masked in reports.

## Six SIL templates × Anthropic surfaces

Each section below is a hypothesis bound to a real, public-facing
surface of Anthropic's products. The surfaces named are based on the
public product UI; the operator should verify the exact URL / endpoint
in their own logged-in session before capturing.

---

### 1. `connector_revoke_persistence` × Anthropic MCP integrations

**Hypothesis.** After revoking an Anthropic-developed MCP connector
from Claude (e.g. a Drive / Notion / GitHub integration), content
sourced through that connector should no longer be retrievable inside
Claude's responses, search, recent-files, or any export the operator
can generate.

**Why this is interesting here.** MCP is a relatively new surface;
the revoke / cache-invalidation paths have had less time to harden
than e.g. legacy OAuth flows.

**Test-data plan.**
- In the third-party service (e.g. Google Drive on your own account),
  create one file named `SIL-PROBE-<rand>-roadmap` containing a
  unique sentence with the probe string.
- Connect that service to Claude via the MCP / Connectors UI.
- Ask Claude a question that should retrieve the probe content;
  confirm the retrieval works pre-revoke.

**`before` capture.**
- HTML of the Connectors settings page (lists the integration).
- JSON / HTML of a Claude response that retrieves the probe.
- HTML of the file browser / source list inside Claude that shows the
  connector's files.

**Transition.**
- Revoke the connector in `claude.ai/settings/connectors` (or the
  equivalent in the current product UI). Record:

  ```bash
  sil transition mark --scenario <id> --type revoked_oauth \
    --note "revoked MCP connector via /settings/connectors at <UTC ts>"
  ```

**`after` capture (immediate).**
- Re-take the three surfaces above with the same questions / queries.

**`delayed_after`.**
- Re-take at 5 min, 1 h, 24 h (cron `sil scheduler run-due`).

**Diff strategy.**
- `sil diff --keyword SIL-PROBE-<rand>` on each pair (HTML, JSON).

**Reportable conditions (per `docs/scenario_playbook.md`).**
- Probe content still retrievable post-revoke beyond the documented
  SLA.
- Probe content present in any export issued *after* revoke.
- API responses still include the connector's content_id /
  source_uri.

**False-positive traps.**
- Anthropic likely caches at multiple layers; wait at least one SLA
  window before drawing conclusions.
- A second connector may point to the same upstream service — revoke
  *all* relevant connectors or you can't attribute persistence.

**Prohibited.**
- Do not enumerate other users' connector_ids.
- Do not call the third-party provider through any path other than
  Anthropic's official UI.

---

### 2. `project_knowledge_deletion` × claude.ai Projects

**Hypothesis.** Files / knowledge items deleted from a Project on
`claude.ai` should be unrecoverable via project file list, in-chat
retrieval, the project export (if any), and any global search.

**Test-data plan.**
- Create one Project on `claude.ai`.
- Upload one file named `SIL-PROBE-<rand>.md` containing the probe
  sentence.
- Run one chat turn that retrieves the probe content; confirm it works.

**`before` capture.**
- HTML of the project file list.
- JSON / HTML of a chat turn that retrieves the probe.
- Screenshot of the project sidebar.

**Transition.**
- Delete the file from the Project UI:

  ```bash
  sil transition mark --scenario <id> --type deleted_file \
    --note "deleted file via project UI at <UTC ts>"
  ```

**`after` / `delayed_after`.** Re-capture the same surfaces.

**Diff strategy.** `sil diff --keyword SIL-PROBE-<rand>` plus
`sil bundle diff` if the product offers a project export.

**Reportable.**
- Probe content surfaces in retrieval after the documented SLA.
- Probe content appears in any project-level audit / activity log
  beyond `{ts, actor, action}` (i.e. the *body* persists, not just
  the name).
- Probe content survives in a fresh export issued post-deletion.

**Traps.** Search re-index windows; per-conversation caching.

---

### 3. `team_permission_downgrade` × claude.ai / console.anthropic.com Workspace

**Hypothesis.** After downgrading a Workspace member from admin to a
lower role, the downgraded member should immediately lose access to
admin-only API responses, settings pages, billing IDs, and audit
endpoints.

**Test-data plan.**
- You own both accounts (yours + a second test account you also own).
- Add the second account to your Workspace as an admin.
- From the second account, capture admin-only surfaces.

**`before` capture (from the second account's session).**
- JSON of API responses available to that session (members list,
  billing customer id, etc.).
- HTML of `/settings/billing` or whatever admin surfaces exist.
- WebSocket transcript only if explicitly allowed by program policy
  (often out of scope).

**Transition.** Downgrade the second account to a member / viewer
from the first account's admin UI.

**`after` capture.** Force a fresh session on the second account
(log out + log in / new tab) and re-capture the same surfaces.

**Diff strategy.** `sil diff --keyword owner_id --keyword billing
--keyword admin` on the JSON pairs.

**Reportable.**
- Downgraded session still returns admin-only IDs (billing customer
  id, owner id, audit endpoints).
- Admin-only pages render content (not just a 200 with empty body).

**Traps.** Stale token / cookie in the second account's session;
refresh before drawing conclusions.

**Prohibited.** Do not test against any session you don't own.

---

### 4. `api_key_rotation_persistence` × console.anthropic.com API keys

**Hypothesis.** After rotating (deleting and recreating) an API key
on `console.anthropic.com`, the previous key should immediately stop
working against `api.anthropic.com`, and the previous key's full
value should never appear in any UI or API response.

**Test-data plan.**
- Mint **TWO** test API keys on your own account.
- Use the first to make one trivial API call (e.g. `/v1/models` if
  that's in scope) and save the response.
- Note the **prefix only** of both keys (e.g. `sk-ant-…AAAA` and
  `sk-ant-…BBBB`). Never store the full secret in a SIL artifact.

**`before` capture.**
- HTML of the API keys page (lists prefix + last-used).
- JSON of the trivial API call signed with key 1.

**Transition.** Delete key 1 from the console.

**`after` capture.**
- Same trivial API call signed with key 1 (expected: auth failure).
- HTML of the API keys page (key 1 should be gone).
- HTML of activity / audit log (if any).

**`delayed_after`.** At the documented grace window (Anthropic's
docs will say). Re-try key 1 against the API.

**Diff strategy.** `sil diff --keyword sk-ant_<prefix1>` —
SIL's `_REDACT_PATTERNS` will redact the prefix in any generated
report, so include the prefix in your operator notes only.

**Reportable.**
- Key 1 still authorized past the documented grace window.
- The full key 1 secret appears anywhere in any UI / API response
  after rotation.

**Traps.** Vendor grace periods are intentional — read the docs
first.

**Prohibited.** Do not store full key secrets in any artifact.

---

### 5. `export_after_deletion` × claude.ai data export (if offered)

**Hypothesis.** A data export requested after deleting an item should
not contain the deleted item's body.

**Test-data plan.**
- Create a Project + upload a file with the probe signature (same as
  scenario 2).
- Trigger a data export *before* the deletion (so you have a
  baseline).

**`before` capture.** Download the pre-deletion export bundle.

**Transition.** Delete the file (and / or the project, depending on
what's offered).

**`after` capture.** Trigger a new export, immediately and at 5m /
1h / 24h.

**Diff strategy.**

```bash
sil bundle diff --before before_export.zip --after after_export.zip \
  --keyword SIL-PROBE-<rand> --scenario <id>
```

**Reportable.**
- Probe body present in any post-deletion export.
- The bundle's signed manifest claims the item is absent but a member
  file inside still contains it.

---

### 6. `delayed_cache_inconsistency` × claude.ai public surfaces / CDN

**Hypothesis.** If `claude.ai` exposes any public-facing surface
(profile pages, shared chat snapshots, public Artifact links), a
deletion / privacy-change transition should converge on the
post-transition state within the documented cache SLA.

**Surfaces to look for in `claude.ai`'s product.**
- Shared chat snapshot URLs (if the product offers "share this
  chat").
- Public Artifact URLs (if the product offers public artifact
  publishing).

**Test-data plan.**
- Create a shareable artifact with the probe signature inside.
- Publish.

**`before` capture.** Fetch the public URL with `curl` from one or
two edges you lawfully control. Record `ETag`, `Last-Modified`,
`Cache-Control` headers.

**Transition.** Unshare / delete / privatize.

**`after` capture (immediate).** Re-fetch the public URL.

**`delayed_after`.** At 5m, 1h, 24h.

**Diff strategy.** `sil diff --keyword SIL-PROBE-<rand>` plus header
comparison.

**Reportable.**
- Stale content served past Anthropic's documented cache SLA.
- One CDN POP serving stale content well after another POP is fresh.

**Prohibited.** No cache-poisoning. No unauthorized proxies.

---

## Picking which scenario to run first

If you have to pick exactly one, I'd start with **#1 (MCP connector
revoke)** for these reasons:

- MCP is the newest of Anthropic's surfaces — least researcher
  attention historically, lowest duplicate risk.
- The hypothesis is operationally simple to set up: 1 file, 1
  connector, 1 query.
- The diff signal is binary: the probe is there or it isn't.
- The fix direction is clear ("invalidate downstream caches on
  revoke"), so a triager has a concrete action to take.

Second choice: **#4 (API key rotation)**, because it's even simpler
(no third-party service involved), and grace-window violations are
unambiguous.

## After you have a finding

1. `sil scenario annotate --scenario <id> --scope https://hackerone.com/anthropic --actual "..." --impact "..."`
2. `sil finding open --scenario <id> --title "<surface>: <invariant> after <transition>" --severity <level> --diff <diff_id>`
3. `sil report generate --scenario <id>` (redacted by default)
4. `sil scenario export --scenario <id>` → a `.zip` you can attach to
   the HackerOne submission.
5. Submit via HackerOne; never DM staff with raw evidence.
6. As the program responds, `sil finding update --status submitted /
   accepted / fixed --external-id <H1 report id> --paid <amount>
   --currency USD`.

## What this document is **not**

- Not legal advice. The authoritative scope is whatever
  <https://hackerone.com/anthropic> says today.
- Not a guarantee any of these scenarios will produce a paid finding.
  Bug Bounty payouts depend on reproducibility, novelty, severity,
  and duplicate status.
- Not a substitute for reading
  [`docs/scenario_playbook.md`](scenario_playbook.md) and
  [`docs/report_quality.md`](report_quality.md) — those documents own
  the per-template rules and the BB-grade reporting bar.
