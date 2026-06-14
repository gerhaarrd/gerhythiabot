from __future__ import annotations

from typing import Any

import aiohttp

from rhythia.api_errors import RhythiaAPIError

BASE_URL = "https://production.rhythia.com/api"


async def public_search(
    *,
    query: str,
    limit: int = 10,
    timeout: float = 30.0,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    """Search Rhythia for players and beatmaps (public endpoint)."""
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with session.post(
            f"{BASE_URL}/enhancedSearch",
            headers={"Content-Type": "application/json"},
            json={"text": query, "limit": limit},
            timeout=client_timeout,
        ) as response:
            try:
                body = await response.json()
            except (ValueError, aiohttp.ContentTypeError) as exc:
                raise RhythiaAPIError(
                    f"Invalid response (HTTP {response.status})",
                    status_code=response.status,
                ) from exc

            if not response.ok:
                raise RhythiaAPIError(
                    f"HTTP {response.status}: {body}",
                    status_code=response.status,
                )
            if not isinstance(body, dict):
                raise RhythiaAPIError("Unexpected response format.")
            return body
    except aiohttp.ClientError as exc:
        raise RhythiaAPIError(f"Network error: {exc}") from exc
    finally:
        if close_session:
            await session.close()


class RhythiaClient:
    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self._timeout = timeout
        # Simple in-memory TTL cache for find_beatmap results: {key: (ts, value)}
        self._beatmap_cache: dict[str, tuple[float, dict[str, Any]] ] = {}
        self._beatmap_cache_ttl = 300.0  # seconds

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _post(self, endpoint: str, **extra: Any) -> dict[str, Any]:
        url = f"{BASE_URL}/{endpoint}"
        payload: dict[str, Any] = {"session": "", **extra}
        headers = {"Content-Type": "application/json"}

        session = await self._ensure_session()
        client_timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=client_timeout,
            ) as response:
                try:
                    body = await response.json()
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise RhythiaAPIError(
                        f"Invalid response (HTTP {response.status})",
                        status_code=response.status,
                    ) from exc

                if not response.ok:
                    detail = body if isinstance(body, str) else body.get("message", body)
                    raise RhythiaAPIError(
                        f"HTTP {response.status}: {detail}",
                        status_code=response.status,
                    )

                if not isinstance(body, dict):
                    raise RhythiaAPIError("Unexpected response format.")

                return body
        except aiohttp.ClientError as exc:
            raise RhythiaAPIError(f"Network error: {exc}") from exc

    async def get_profile(self, *, user_id: int | None = None) -> dict[str, Any]:
        if user_id is not None:
            return await self._post("getProfile", id=user_id)
        return await self._post("getProfile")

    async def get_user_scores(self, *, user_id: int) -> dict[str, Any]:
        return await self._post("getUserScores", id=user_id)

    async def get_score(self, *, score_id: int) -> dict[str, Any]:
        return await self._post("getScore", id=score_id)

    async def find_beatmap(self, query: str) -> dict[str, Any] | None:
        # Check cache first
        key = (query or "").strip()
        now = __import__("time").time()
        cached = self._beatmap_cache.get(key)
        if cached:
            ts, val = cached
            if now - ts < self._beatmap_cache_ttl:
                return val
            else:
                del self._beatmap_cache[key]
        # First try the public search (enhancedSearch) which is fast for titles
        try:
            results = await self.search(query=query.strip(), limit=10)
            beatmaps = results.get("beatmaps") or []
        except Exception:
            beatmaps = []

        if not isinstance(beatmaps, list) or not beatmaps:
            try:
                beatmaps_page = await self.get_beatmaps(page=1, query=query.strip())
                beatmaps = beatmaps_page.get("beatmaps") or []
            except Exception:
                return None

        if not isinstance(beatmaps, list) or not beatmaps:
            return None

        # If query is numeric, try to match by id from the search results
        if query.strip().isdigit():
            beatmap_id = int(query.strip())
            for beatmap in beatmaps:
                if isinstance(beatmap, dict) and beatmap.get("id") == beatmap_id:
                    candidate = beatmap
                    break
            else:
                candidate = None
        else:
            candidate = beatmaps[0] if isinstance(beatmaps[0], dict) else None

        if candidate is None:
            return None

        # If the candidate already contains detailed fields like playcount,
        # return it. Otherwise try a single `getBeatmaps` call to enrich the
        # candidate (this endpoint often includes playcount and more metadata).
        has_playcount = "playcount" in candidate or "playCount" in candidate or "play_count" in candidate
        if has_playcount:
            return candidate

        try:
            # Query getBeatmaps by title to find a richer representation.
            title = candidate.get("title") or query
            beatmaps_page = await self.get_beatmaps(page=1, query=title)
            candidates = beatmaps_page.get("beatmaps") or []
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                if c.get("id") == candidate.get("id") or (c.get("title") or "") == (candidate.get("title") or ""):
                    # Merge c into candidate, preferring values from c when present
                    merged = {**candidate, **c}
                    self._beatmap_cache[key] = (now, merged)
                    return merged
        except Exception:
            # If enrichment fails, just return the original candidate
            self._beatmap_cache[key] = (now, candidate)
            return candidate

        self._beatmap_cache[key] = (now, candidate)
        return candidate

    async def get_beatmaps(
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
        **extra: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page": page,
            "textFilter": query,
            "authorFilter": author,
            "tagsFilter": tags,
            "minStars": min_stars,
            "maxStars": max_stars,
            "status": status,
            **extra,
        }
        if creator_id is not None:
            payload["creator"] = creator_id
        return await self._post("getBeatmaps", **payload)

    async def get_leaderboard(
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
        return await self._post("getLeaderboard", **payload)

    async def search(self, *, query: str, limit: int = 10) -> dict[str, Any]:
        session = await self._ensure_session()
        return await public_search(query=query, limit=limit, timeout=self._timeout, session=session)

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> RhythiaClient:
        await self._ensure_session()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()