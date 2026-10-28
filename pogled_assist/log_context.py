"""Bounded context snapshots copied at destination admission boundaries."""

CONTEXT_EVENTS = frozenset(
    {
        "runtime",
        "gaze_settings",
        "screen_mapping",
        "selection_settings",
        "selection_state",
        "target_geometry",
    }
)


def update_context(snapshots, name, fields):
    key = name, fields.get("source", fields.get("surface"))
    if name == "target_geometry":
        key = _geometry_key(snapshots, fields)
    if name == "selection_end":
        snapshots.pop(("selection_state", fields.get("source")), None)
    elif name in CONTEXT_EVENTS and (key in snapshots or len(snapshots) < 32):
        snapshots[key] = {"event": name, "data": fields}


def _geometry_key(snapshots, fields):
    context = fields.get("context_id")
    for old, snapshot in tuple(snapshots.items()):
        if _old_geometry(snapshot, fields):
            snapshots.pop(old)
    targets = tuple(
        target.get("target_id") for target in fields.get("targets", []) if isinstance(target, dict)
    )
    return "target_geometry", context, targets


def _old_geometry(snapshot, fields):
    if snapshot["event"] != "target_geometry":
        return False
    same_surface = snapshot["data"].get("kind") == fields.get("kind")
    return same_surface and snapshot["data"].get("context_id") != fields.get("context_id")
