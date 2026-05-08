# Scenario Playbook

Each playbook below corresponds to a key in `SCENARIO_TEMPLATE_LIBRARY`
(`sil scenario list-templates` to see them all). Run
`sil scenario show-template <key>` to see the same fields rendered to your
terminal.

The playbooks are intentionally **defensive**: they describe what to look
for, not how to bypass auth. None of them require any non-public API or
unauthorized-login automation.

---

## 1. `connector_revoke_persistence`

**Hypothesis.** After revoking a third-party connector (Drive, Notion,
Slack, GitHub, etc.), content sourced from that connector should disappear
from search, retrieval, history, and exports across all surfaces.

**Prerequisites.**
- You own the account that the connector is bound to.
- You have already created a uniquely identifiable test document via the
  connector — for example, a Google Doc named
  `SIL-PROBE-{shortuuid}-do-not-share`.
- You have re-read the program's scope statement for third-party
  integrations (some treat the connector as out-of-scope).

**Test data.**
- One file / message / page in the third-party service that contains a
  unique signature string you control.
- Optional: a second document in another connector to ensure your diff
  catches the right one.

**`before` observation.**
- HTML or screenshot of the in-app search page showing the connector's
  document.
- JSON observation of the retrieval API response when you query for the
  signature string.
- An export / data dump that includes the connector's content.

**Transition.**
- `sil transition mark --scenario <id> --type revoked_oauth --note "revoked Google Drive connector via /settings/connectors"`
- You manually click "Revoke" in the target service.

**`after` observation.**
- The exact same three surfaces. Same query, same export options, same
  selectors.

**`delayed_after` observation.**
- 5m: search and retrieval (the fast cache).
- 1h: search, retrieval, export.
- 24h: full export bundle.

**Diffs.**
- `sil diff` on the JSON / HTML pairs with `--keyword <signature>` and
  `--keyword <connector_name>`.
- `sil bundle diff` on the export bundles with `--keyword <signature>`.

**Reportable.**
- Connector-sourced content is still searchable / retrievable post-revoke.
- API responses still include the connector's `content_id` / `source_uri`.
- Exports requested AFTER revoke include the connector's documents.
- Caches converge later than the documented SLA.

**False-positive traps.**
- The vendor caches embeddings; a queue may still contain in-flight items.
  Wait one full SLA window before reporting.
- Trash / Recycle bins are intentionally retained — check policy first.
- A second connector points to the same source — revoke order matters.

**Prohibited actions.**
- Do not access the third-party provider's content through any other path.
- Do not exercise the connector's grant flow against another user.

---

## 2. `project_knowledge_deletion`

**Hypothesis.** Files / knowledge items deleted from a project should be
unrecoverable via UI, search, retrieval, and exports.

**Prerequisites.**
- You own / admin the project and uploaded the test artifact yourself.
- The artifact contains a unique signature string (`SIL-DELETE-<rand>`).

**Test data.**
- One uploaded file with the signature string in its body.
- Optional: a second non-deleted file as a control.

**`before` observation.**
- Project file list (HTML / API).
- Search result for the signature string.
- Export bundle.

**Transition.**
- `sil transition mark --type deleted_file --note "deleted via UI from project_settings"`

**`after` observation.**
- Same three surfaces, plus the activity / audit log if available.

**`delayed_after`.**
- 5m: search.
- 1h: search, retrieval, export.
- 24h: full export.

**Diffs.**
- `sil diff --keyword SIL-DELETE-<rand>` on each pair.
- `sil bundle diff --keyword SIL-DELETE-<rand>` on exports.

**Reportable.**
- The deleted artifact's body / chunks appear in retrieval / search past
  the documented SLA.
- Audit log fields beyond `{ts, actor, action}` contain the deleted item's
  body (not just its name).
- Exports include the deleted artifact's body.

**False-positive traps.**
- Audit logs intentionally keep the *name* of deleted items; only flag if
  the *body* persists.
- Server-side search indexes have a 5-15m re-index window.

**Prohibited actions.**
- Do not test on a project shared with users you don't have permission to
  observe.

---

## 3. `team_permission_downgrade`

**Hypothesis.** After downgrading a member from admin to viewer, the
member should lose all admin-only views and IDs.

**Prerequisites.**
- You own / admin the team.
- You have a SECOND test account *that you also own* playing the role of
  the downgraded user. Both accounts must be yours.

**Test data.**
- The team has at least one admin-only entity (a billing customer id, an
  audit log endpoint, an admin-scoped webhook).

**`before` observation.**
- HTML / screenshot of the admin-only pages from the second account.
- JSON capture of API responses available to that account's session.
- WebSocket / live-update channel transcripts (if the program allows
  capturing them; otherwise skip).

**Transition.**
- `sil transition mark --type downgraded_permission --note "downgraded second account from admin to viewer"`

**`after` observation.**
- Reload the second account's session (force a fresh token), capture the
  same surfaces.

**`delayed_after`.**
- 5m, 1h, 24h: API responses only (UI behavior usually converges quickly).

**Diffs.**
- `sil diff` on JSON pairs with `--keyword owner_id --keyword billing
  --keyword audit`.

**Reportable.**
- Admin-only IDs leak in API responses to the downgraded user.
- Admin-only pages render content (not just an empty 200) for the
  downgraded user.
- Live-update channels still push admin events to the downgraded user.

**False-positive traps.**
- The UI hides links but the API still works — that *is* the bug.
- Stale tab / token: refresh the second account's session before drawing
  conclusions.

**Prohibited actions.**
- Do not test against a session belonging to anyone other than yourself.

---

## 4. `api_key_rotation_persistence`

**Hypothesis.** After rotating an API key, the previous key prefix should
disappear from dashboards, logs, and webhooks.

**Prerequisites.**
- Both the old and new keys are yours.
- You captured the old key's *prefix only* (e.g. `sk_live_abcd…`), never
  the full secret, in artifacts.

**Test data.**
- A small webhook receiver you control (ngrok / your own server) that logs
  signature header prefixes only.

**`before` observation.**
- Dashboard listing of keys (HTML).
- Logs / activity feed (JSON / HTML).

**Transition.**
- `sil transition mark --type rotated_api_key --note "rotated via /settings/keys"`

**`after` observation.**
- Same surfaces, plus a webhook payload triggered intentionally.

**`delayed_after`.**
- 5m: webhook payloads.
- 1h: dashboard, logs.
- 24h: confirm the documented grace window has expired before retrying the
  old key.

**Diffs.**
- `sil diff` on JSON pairs with `--keyword sk_ --keyword key_`.

**Reportable.**
- Old key still authorized past the documented grace period.
- Old key's *full* value appears in any UI / API response.
- Webhook signatures continue to validate using the old key's secret.

**False-positive traps.**
- Vendors often allow a deliberate grace window — read the docs first.
- Audit log keeping the *prefix* is normal; full-secret leaks are not.

**Prohibited actions.**
- Do not store live key secrets in any SIL artifact, even temporarily.
- Do not retry an authorized-then-rotated key against unrelated endpoints
  to "see what works".

---

## 5. `export_after_deletion`

**Hypothesis.** Exports requested after a deletion should not contain the
deleted item.

**Prerequisites.**
- You own the data and the export was requested by your account.
- The deleted artifact has a unique signature string.

**Test data.**
- One uploaded file with a signature string.
- Optional: a kept file as a control.

**`before` observation.**
- Export requested before the deletion.

**Transition.**
- `sil transition mark --type deleted_file --note "deleted file before export"`

**`after` observation.**
- Export requested immediately after the deletion.

**`delayed_after`.**
- Re-pull at 5m, 1h, 24h.

**Diffs.**
- `sil bundle diff --keyword <signature>` on each pair.

**Reportable.**
- Post-deletion export contains the deleted item's body or chunks.
- The bundle's signed manifest claims the item is absent but a member file
  still contains it.

**False-positive traps.**
- Some vendors snapshot the export at request time, not finish time.
- Audit log mention of the deleted name is generally allowed.

**Prohibited actions.**
- Do not request an export of someone else's account, even if you can.

---

## 6. `delayed_cache_inconsistency`

**Hypothesis.** Caches and CDNs should converge on the post-transition
state within the documented SLA (5m / 1h / 24h).

**Prerequisites.**
- You can reach the same edges your real users reach (no privileged
  backdoor).
- You have the vendor's documented cache SLA in writing.

**Test data.**
- Any item the vendor caches at the edge: a public profile, a public
  document, an org logo.

**`before` observation.**
- Capture the resource and its `Etag` / `Last-Modified` / `Cache-Control`
  headers.

**Transition.**
- The mutation that should invalidate the cache (rename, delete, change
  visibility).

**`after` observation.**
- Re-fetch from each POP / region you can lawfully reach.

**`delayed_after`.**
- 5m, 1h, 24h via `sil scheduler run-due`.

**Diffs.**
- `sil diff` on the HTML / JSON pairs with `--keyword <old_value>`.

**Reportable.**
- Stale data is still served past the documented SLA.
- ETag / Last-Modified do not reflect the transition time.
- Vary headers cause one user-agent to see stale data while another sees
  fresh.

**False-positive traps.**
- Your local browser cache, not the CDN.
- CDN POPs differ; one POP may be briefly ahead of another.

**Prohibited actions.**
- Do not attempt CDN cache poisoning.
- Do not use unauthorized proxies.
