"""Built-in scenario templates.

Each template captures a state-transition class that has produced real
post-transition residuals in the wild. The fields below are the playbook
skeleton for that scenario; the long-form playbook lives in
`docs/scenario_playbook.md` and the methodology in `docs/methodology.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScenarioTemplate:
    key: str
    title: str
    hypothesis: str
    suggested_transitions: tuple[str, ...]
    suggested_observations: tuple[str, ...]
    persistence_keywords: tuple[str, ...]
    prerequisites: tuple[str, ...] = field(default_factory=tuple)
    reportable_conditions: tuple[str, ...] = field(default_factory=tuple)
    false_positive_traps: tuple[str, ...] = field(default_factory=tuple)
    prohibited_actions: tuple[str, ...] = field(default_factory=tuple)
    recommended_fix_direction: str = ""

    def show_lines(self) -> list[str]:
        out = [
            f"# {self.title}",
            f"key: {self.key}",
            "",
            "## Hypothesis",
            self.hypothesis,
            "",
        ]
        if self.prerequisites:
            out.append("## Prerequisites")
            out.extend(f"- {p}" for p in self.prerequisites)
            out.append("")
        if self.suggested_transitions:
            out.append("## Suggested transitions")
            out.extend(f"- {t}" for t in self.suggested_transitions)
            out.append("")
        if self.suggested_observations:
            out.append("## Suggested observations")
            out.extend(f"- {o}" for o in self.suggested_observations)
            out.append("")
        if self.persistence_keywords:
            out.append("## Persistence keywords (for `sil diff --keyword`)")
            out.extend(f"- {k}" for k in self.persistence_keywords)
            out.append("")
        if self.reportable_conditions:
            out.append("## Reportable conditions")
            out.extend(f"- {c}" for c in self.reportable_conditions)
            out.append("")
        if self.false_positive_traps:
            out.append("## False-positive traps")
            out.extend(f"- {t}" for t in self.false_positive_traps)
            out.append("")
        if self.prohibited_actions:
            out.append("## Prohibited actions (do NOT do these)")
            out.extend(f"- {a}" for a in self.prohibited_actions)
            out.append("")
        if self.recommended_fix_direction:
            out.append("## Recommended fix direction")
            out.append(self.recommended_fix_direction)
            out.append("")
        return out


_PROHIBITED_BASELINE: tuple[str, ...] = (
    "Do not bypass authentication, MFA, or rate limits.",
    "Do not target other users' accounts or test outside your authorized scope.",
    "Do not run automated tooling at high concurrency or rates that resemble DoS.",
    "Do not exfiltrate live customer data; redact identifiers before sharing.",
)


SCENARIO_TEMPLATE_LIBRARY: dict[str, ScenarioTemplate] = {
    "connector_revoke_persistence": ScenarioTemplate(
        key="connector_revoke_persistence",
        title="Connector revoke persistence",
        hypothesis=(
            "After revoking a third-party connector, content sourced from that "
            "connector should disappear from search, retrieval, history, and "
            "exports across all surfaces."
        ),
        suggested_transitions=("revoked_oauth",),
        suggested_observations=(
            "List of connector-sourced documents (before).",
            "Search UI results for a known connector keyword (before & after).",
            "Export / data dump (before & after, plus 5m / 1h / 24h re-pulls).",
        ),
        persistence_keywords=("connector", "oauth", "drive", "notion", "slack"),
        prerequisites=(
            "You own the account that the connector is bound to.",
            "You created or imported a uniquely identifiable test document via the connector.",
            "You have re-read the program's scope statement for third-party integrations.",
        ),
        reportable_conditions=(
            "Connector-sourced content is still searchable / retrievable post-revoke.",
            "API responses still include the connector's content_id or source_uri.",
            "Exports requested AFTER revoke contain content sourced through the revoked connector.",
            "Caches converge later than the documented SLA.",
        ),
        false_positive_traps=(
            "The vendor caches embeddings; your queue may still contain in-flight items.",
            "Trash / Recycle bin is intentionally retained by design — check policy first.",
            "A second connector points to the same source — revoke order matters.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE
        + ("Do not access the third-party provider's content through any other path.",),
        recommended_fix_direction=(
            "On revoke, invalidate downstream caches and search indexes; ensure that "
            "exports use a post-revoke snapshot, not a pre-revoke one."
        ),
    ),
    "project_knowledge_deletion": ScenarioTemplate(
        key="project_knowledge_deletion",
        title="Project knowledge deletion",
        hypothesis=(
            "Files / knowledge items deleted from a project should be unrecoverable "
            "via UI, search, retrieval, and exports."
        ),
        suggested_transitions=("deleted_file",),
        suggested_observations=(
            "Project file list (before & after).",
            "Search results for the deleted filename / unique phrase.",
            "Export bundle (before & after; plus 24h re-pull).",
            "Activity / audit log entries that reference the deleted item.",
        ),
        persistence_keywords=("deleted", "removed", "filename"),
        prerequisites=(
            "You own / admin the project and uploaded the test artifact yourself.",
            "The artifact contains a unique signature string you control (e.g. `SIL-DELETE-<rand>`).",
        ),
        reportable_conditions=(
            "Deleted artifact still appears in retrieval / search after the documented SLA.",
            "Audit log fields beyond {ts, actor, action} contain the deleted item's payload.",
            "Exports include the deleted artifact's body / chunks.",
        ),
        false_positive_traps=(
            "Audit logs intentionally keep the *name* of deleted items; only flag if the *body* persists.",
            "Server-side search indexes have a 5-15m re-index window — do not report under SLA.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE,
        recommended_fix_direction=(
            "Tombstone the artifact in the index and ensure exports honor tombstones; "
            "purge cache / CDN entries on delete."
        ),
    ),
    "team_permission_downgrade": ScenarioTemplate(
        key="team_permission_downgrade",
        title="Team permission downgrade",
        hypothesis=(
            "After downgrading a member from admin to viewer, the member should "
            "lose all admin-only views and IDs."
        ),
        suggested_transitions=("downgraded_permission",),
        suggested_observations=(
            "Settings pages visible to the member (before & after).",
            "API responses available to the member's session.",
            "Member's audit-log endpoints, if any.",
        ),
        persistence_keywords=("admin", "owner_id", "billing", "audit"),
        prerequisites=(
            "You own / admin the team and a SECOND test account you control plays the downgraded user.",
            "Both accounts are yours; do not test against another person's session.",
        ),
        reportable_conditions=(
            "Admin-only IDs (billing customer id, owner id, etc.) leak in API responses to the downgraded user.",
            "Admin-only pages render content (not just a 200 with empty body) for the downgraded user.",
            "WebSocket / live-update channels still push admin events to the downgraded user.",
        ),
        false_positive_traps=(
            "The UI sometimes hides links but the API still works — that is the bug, not the absence of a link.",
            "Stale tab / token: refresh the second account's session before drawing conclusions.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE
        + ("Do not test against another person's session — use a second account you own.",),
        recommended_fix_direction=(
            "Enforce permission checks at the data layer (API / DB) and invalidate "
            "live channels on permission change."
        ),
    ),
    "api_key_rotation_persistence": ScenarioTemplate(
        key="api_key_rotation_persistence",
        title="API key rotation persistence",
        hypothesis=(
            "After rotating an API key, the previous key prefix should disappear "
            "from dashboards, logs, and webhooks."
        ),
        suggested_transitions=("rotated_api_key",),
        suggested_observations=(
            "Dashboard listing of keys (before & after).",
            "Logs / activity feed (before & after).",
            "Webhook receiver: payloads triggered by the old key.",
        ),
        persistence_keywords=("sk_", "key_", "token"),
        prerequisites=(
            "Both the old and new keys are yours.",
            "You captured the old key's prefix only (e.g. `sk_live_abcd...`), never the full secret, in artifacts.",
        ),
        reportable_conditions=(
            "Old key is still accepted by the API after the documented grace period.",
            "Old key's full value appears in any UI / API response after rotation.",
            "Webhook signatures continue to validate using the old key's secret.",
        ),
        false_positive_traps=(
            "Vendors often allow a deliberate grace window (e.g. 24h) — read the docs first.",
            "Audit log keeping the *prefix* is normal; only flag full-secret leaks.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE
        + ("Do not store live key secrets in any SIL artifact, even temporarily.",),
        recommended_fix_direction=(
            "Atomically invalidate the old key on rotation; redact secrets, not just "
            "prefixes, from logs."
        ),
    ),
    "export_after_deletion": ScenarioTemplate(
        key="export_after_deletion",
        title="Export after deletion",
        hypothesis=(
            "Exports requested after a deletion should not contain the deleted item."
        ),
        suggested_transitions=("deleted_file",),
        suggested_observations=(
            "Export requested before deletion.",
            "Export requested immediately after deletion.",
            "Export requested 5m / 1h / 24h after deletion.",
        ),
        persistence_keywords=("deleted", "filename"),
        prerequisites=(
            "You own the data and the export was requested by your account.",
            "The deleted artifact has a unique signature string you control.",
        ),
        reportable_conditions=(
            "Post-deletion export contains the deleted item's body or chunks.",
            "Audit_log entries inside the bundle contain payload bodies (beyond {ts, actor, action}).",
            "The bundle's signed manifest claims the item is absent but a member file still contains it.",
        ),
        false_positive_traps=(
            "Some vendors snapshot the export at request time, not finish time — a race here is by design.",
            "Audit log mention of the deleted name is generally allowed; the body is not.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE,
        recommended_fix_direction=(
            "Build the export from a post-deletion snapshot; cross-check audit_log "
            "vs documents.json before sealing the bundle."
        ),
    ),
    "delayed_cache_inconsistency": ScenarioTemplate(
        key="delayed_cache_inconsistency",
        title="Delayed cache inconsistency",
        hypothesis=(
            "Caches and CDNs should converge on the post-transition state within "
            "the documented SLA (e.g. 5m / 1h / 24h)."
        ),
        suggested_transitions=("deleted_file", "revoked_oauth", "downgraded_permission"),
        suggested_observations=(
            "Observe immediately after transition.",
            "Re-observe at 5m, 1h, 24h via `sil scheduler run-due`.",
        ),
        persistence_keywords=("cache", "cdn", "etag"),
        prerequisites=(
            "You can reach the same edges your real users reach (no privileged backdoor).",
            "You have the vendor's documented cache SLA in writing.",
        ),
        reportable_conditions=(
            "Stale data is still served past the documented SLA.",
            "ETag / Last-Modified headers do not reflect the transition time.",
            "Vary headers cause one user-agent to see stale data while another sees fresh.",
        ),
        false_positive_traps=(
            "Your local browser cache, not the CDN — clear it before re-observing.",
            "CDN POPs differ; one POP may be ahead of another. Average across POPs you can lawfully reach.",
        ),
        prohibited_actions=_PROHIBITED_BASELINE
        + ("Do not attempt CDN cache poisoning or use of unauthorized proxies.",),
        recommended_fix_direction=(
            "Issue purge / soft-purge calls on transition; align Cache-Control + Vary "
            "with the SLA you advertise."
        ),
    ),
}


def list_templates() -> list[ScenarioTemplate]:
    return list(SCENARIO_TEMPLATE_LIBRARY.values())


def get_template(key: str) -> ScenarioTemplate | None:
    return SCENARIO_TEMPLATE_LIBRARY.get(key)
