"""Built-in scenario templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioTemplate:
    key: str
    title: str
    hypothesis: str
    suggested_transitions: tuple[str, ...]
    suggested_observations: tuple[str, ...]
    persistence_keywords: tuple[str, ...]


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
            "Export / data dump (before & after).",
        ),
        persistence_keywords=("connector", "oauth", "drive", "notion", "slack"),
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
            "Export bundle (before & after).",
        ),
        persistence_keywords=("deleted", "removed", "filename"),
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
        ),
        persistence_keywords=("admin", "owner_id", "billing", "audit"),
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
        ),
        persistence_keywords=("sk_", "key_", "token"),
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
            "Export requested after deletion.",
            "Export requested 24h after deletion.",
        ),
        persistence_keywords=("deleted", "filename"),
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
            "Re-observe at 5m, 1h, 24h.",
        ),
        persistence_keywords=("cache", "cdn", "etag"),
    ),
}


def list_templates() -> list[ScenarioTemplate]:
    return list(SCENARIO_TEMPLATE_LIBRARY.values())


def get_template(key: str) -> ScenarioTemplate | None:
    return SCENARIO_TEMPLATE_LIBRARY.get(key)
