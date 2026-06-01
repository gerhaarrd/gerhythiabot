from __future__ import annotations

from typing import Any

import requests

from rhythia.api_errors import RhythiaAPIError

BASE_URL = "https://production.rhythia.com/api"


def public_search(*, query: str, limit: int = 10, timeout: float = 30.0) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{BASE_URL}/enhancedSearch",
            headers={"Content-Type": "application/json"},
            json={"session": "", "text": query, "limit": limit},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RhythiaAPIError(f"Network error: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise RhythiaAPIError(
            f"Invalid response (HTTP {response.status_code})",
            status_code=response.status_code,
        ) from exc

    if not response.ok:
        raise RhythiaAPIError(
            f"HTTP {response.status_code}: {body}",
            status_code=response.status_code,
        )
    if not isinstance(body, dict):
        raise RhythiaAPIError("Unexpected response format.")
    return body


class RhythiaClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout

    def _post(self, endpoint: str, **extra: Any) -> dict[str, Any]:
        url = f"{BASE_URL}/{endpoint}"
        payload: dict[str, Any] = {"session": "", **extra}
        headers = {"Content-Type": "application/json"}

        try:
            response = self._session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise RhythiaAPIError(f"Network error: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise RhythiaAPIError(
                f"Invalid response (HTTP {response.status_code})",
                status_code=response.status_code,
            ) from exc

        if not response.ok:
            detail = body if isinstance(body, str) else body.get("message", body)
            raise RhythiaAPIError(
                f"HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )

        if not isinstance(body, dict):
            raise RhythiaAPIError("Unexpected response format.")

        return body

    def get_profile(self, *, user_id: int | None = None) -> dict[str, Any]:
        if user_id is not None:
            return self._post("getProfile", id=user_id)
        return self._post("getProfile")

    def get_user_scores(self, *, user_id: int) -> dict[str, Any]:
        return self._post("getUserScores", id=user_id)

    def find_beatmap(self, query: str) -> dict[str, Any] | None:
        results = self.search(query=query.strip(), limit=10)
        beatmaps = results.get("beatmaps") or []
        if not isinstance(beatmaps, list) or not beatmaps:
            return None

        if query.strip().isdigit():
            beatmap_id = int(query.strip())
            for beatmap in beatmaps:
                if isinstance(beatmap, dict) and beatmap.get("id") == beatmap_id:
                    return beatmap

        first = beatmaps[0]
        return first if isinstance(first, dict) else None

    def get_beatmaps(
        self,
        *,
        page: int = 1,
        query: str = "",
        author: str = "",
        tags: str = "",
        status: str = "",
        min_stars: float = 0,
        max_stars: float = 20,
        creator_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "textFilter": query,
            "authorFilter": author,
            "tagsFilter": tags,
            "minStars": min_stars,
            "maxStars": max_stars,
            "status": status,
        }
        if creator_id is not None:
            payload["creator"] = creator_id
        return self._post("getBeatmaps", **payload)

    def get_leaderboard(
        self,
        *,
        page: int = 1,
        country: str | None = None,
        spin: bool = False,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "spin": spin,
            "include_inactive": include_inactive,
        }
        if country:
            payload["flag"] = country.upper()
        return self._post("getLeaderboard", **payload)

    def search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        return public_search(query=query, limit=limit, timeout=self._timeout)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> RhythiaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
