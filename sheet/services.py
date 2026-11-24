"""The Services page: services (not vessels or money lines) as a work list, with what each one is missing."""


def stamp_completed(service, old_status, now):
    """completed_at follows the status, never the payload: it becomes Completed -> now; it leaves Completed -> None;
    otherwise unchanged (a save that keeps it Completed keeps its time)."""
    if service.status == "completed":
        if old_status != "completed" or service.completed_at is None:
            service.completed_at = now
    else:
        service.completed_at = None
