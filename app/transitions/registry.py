"""Catalog of state transitions the operator can mark."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransitionSpec:
    name: str
    description: str
    typical_followups: tuple[str, ...]


KNOWN_TRANSITIONS: dict[str, TransitionSpec] = {
    "revoked_oauth": TransitionSpec(
        name="revoked_oauth",
        description="OAuth / connector access was revoked from the integrations panel.",
        typical_followups=(
            "Search UI for connector-derived content.",
            "Check exports for content sourced from the connector.",
            "Re-check after 1h / 24h for cache lag.",
        ),
    ),
    "deleted_file": TransitionSpec(
        name="deleted_file",
        description="A file / project knowledge entry was deleted by the owner.",
        typical_followups=(
            "Search UI for the deleted filename.",
            "Trigger an export and inspect for residual content.",
            "Check that retrieval / RAG no longer surfaces the content.",
        ),
    ),
    "removed_user_from_workspace": TransitionSpec(
        name="removed_user_from_workspace",
        description="A user was removed from a workspace / team.",
        typical_followups=(
            "Verify the removed user can no longer see workspace content.",
            "Check audit log entries reference the removal.",
            "Re-check after a delay for stale session tokens.",
        ),
    ),
    "downgraded_permission": TransitionSpec(
        name="downgraded_permission",
        description="A user's permission was reduced (e.g. admin -> viewer).",
        typical_followups=(
            "Confirm previously editable resources are now read-only.",
            "Confirm previously visible IDs / paths are no longer leaked.",
        ),
    ),
    "rotated_api_key": TransitionSpec(
        name="rotated_api_key",
        description="An API key / secret was rotated.",
        typical_followups=(
            "Confirm old key is rejected.",
            "Check that logs / dashboards no longer show old key prefixes.",
        ),
    ),
    "changed_workspace": TransitionSpec(
        name="changed_workspace",
        description="Workspace / team membership or settings changed.",
        typical_followups=(
            "Verify content scoping is correct after the change.",
        ),
    ),
}


def list_transitions() -> list[TransitionSpec]:
    return list(KNOWN_TRANSITIONS.values())


def get_transition_spec(name: str) -> TransitionSpec | None:
    return KNOWN_TRANSITIONS.get(name)
