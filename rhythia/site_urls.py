"""URLs públicas do site rhythia.com."""

SITE_BASE = "https://rhythia.com"


def user_profile_url(user_id: int | str) -> str:
    return f"{SITE_BASE}/player/{user_id}"


def beatmap_page_url(beatmap_id: int | str) -> str:
    return f"{SITE_BASE}/maps/{beatmap_id}"


def leaderboard_page_url(*, country: str | None = None) -> str:
    if country:
        return f"{SITE_BASE}/leaderboards/{country.upper()}"
    return f"{SITE_BASE}/leaderboards"
