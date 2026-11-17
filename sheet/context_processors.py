"""Template context for every page."""

THEMES = {"light", "dark"}


def theme(request):
    """The colour mode the user picked (the `theme` cookie, set by the sidebar switch); "" follows the computer."""
    value = request.COOKIES.get("theme", "")
    return {"theme": value if value in THEMES else ""}
