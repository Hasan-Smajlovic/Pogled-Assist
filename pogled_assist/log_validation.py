"""Validate optional diagnostic fields before they reach analysis indexes."""

STRING_FIELDS = frozenset(
    {
        "attempt_id",
        "surface",
        "source",
        "coverage",
        "outcome",
        "phase",
        "settings_id",
        "context_id",
        "target_id",
        "action_id",
        "origin",
        "observation_id",
        "observation_stream_id",
    }
)


def diagnostic_fields_valid(data: dict) -> bool:
    if any(
        value is not None and not isinstance(value, str)
        for key, value in data.items()
        if key in STRING_FIELDS
    ):
        return False
    sessions = data.get("observation_start_sessions")
    if sessions is not None and (
        not isinstance(sessions, list)
        or len(sessions) > 2
        or not all(isinstance(session, str) for session in sessions)
    ):
        return False
    snapshot = data.get("snapshot")
    if snapshot is None:
        return True
    if not isinstance(snapshot, dict):
        return False
    fields = snapshot.get("data")
    return isinstance(fields, dict) and diagnostic_fields_valid(fields)
