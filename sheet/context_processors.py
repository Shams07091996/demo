"""Template context for every page."""

from . import branding

THEMES = {"light", "dark"}


def theme(request):
    """The colour mode the user picked (the `theme` cookie, set by the sidebar switch); "" follows the computer."""
    value = request.COOKIES.get("theme", "")
    return {"theme": value if value in THEMES else ""}


def brand(request):
    """Whether the company logo (brand.png in the letterhead folder) can be shown; else pages show the anchor."""
    return {"brand_logo": branding.logo_available()}
