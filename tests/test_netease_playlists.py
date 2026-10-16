"""Current playlist payloads: sparse tracks, bounded pages and public metadata only."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from companion_agent.integrations.netease_catalog import NetEaseCatalog


def song(identifier: int) -> dict[str, Any]:
    return {
        "id": identifier,
        "name": f"合成曲目{identifier}",
        "ar": [{"name": "合成歌手"}],
        "al": {"name": "合成专辑"},
        "mp3Url": "DO_NOT_FORWARD",
        "private": "DO_NOT_FORWARD",
    }


def test_sparse_playlist_uses_selected_ids_and_preserves_order() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "music.163.com"
        assert "cookie" not in request.headers
        requests.append(request)
        if request.url.path == "/api/v6/playlist/detail":
            assert request.url.params["n"] == "25"
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "playlist": {
                        "id": 88,
                        "name": "合成歌单",
                        "trackCount": 100,
                        "trackIds": [{"id": i} for i in range(1, 101)],
                        "tracks": [song(i) for i in range(1, 7)],
                    },
                },
            )
        assert request.url.path == "/api/song/detail/"
        ids = json.loads(request.url.params["ids"])
        assert ids == list(range(7, 26)), "Only missing IDs in this page may be fetched"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "songs": [
                    song(9999),
                    *[song(i) for i in reversed(ids)],
                ],
            },
        )

    result = asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).playlist_songs("88", 20, 5))
    assert len(requests) == 2
    assert [s["id"] for s in result["songs"]] == [str(i) for i in range(6, 26)]
    assert result["returned"] == 20 and result["total"] == 100 and result["partial"]
    assert result["unavailable_tracks"] == 0
    assert "DO_NOT_FORWARD" not in json.dumps(result)


def test_unavailable_track_is_reported_without_substituting_other_songs() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v6/playlist/detail":
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "playlist": {
                        "id": 88,
                        "trackCount": 3,
                        "trackIds": [{"id": i} for i in [1, 2, 3]],
                        "tracks": [song(1)],
                    },
                },
            )
        return httpx.Response(200, json={"code": 200, "songs": [song(3), song(999)]})

    result = asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).playlist_songs("88"))
    assert [s["id"] for s in result["songs"]] == ["1", "3"]
    assert result["unavailable_tracks"] == 1 and result["partial"]


@pytest.mark.parametrize("total,offset", [(0, 0), (3, 3)])
def test_empty_or_finished_page_does_not_fetch_more_metadata(total: int, offset: int) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v6/playlist/detail"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "playlist": {
                    "id": 88,
                    "trackCount": total,
                    "trackIds": [{"id": i + 1} for i in range(total)],
                    "tracks": [],
                },
            },
        )

    result = asyncio.run(
        NetEaseCatalog(httpx.MockTransport(respond)).playlist_songs("88", 20, offset)
    )
    assert result["songs"] == [] and result["unavailable_tracks"] == 0


@pytest.mark.parametrize("ids", [[{"id": 1}], []])
def test_inaccessible_nonempty_collection_is_not_reported_as_empty(ids: list[Any]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v6/playlist/detail":
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "playlist": {
                        "id": 88,
                        "trackCount": 1,
                        "trackIds": ids,
                        "tracks": [],
                    },
                },
            )
        return httpx.Response(200, json={"code": 200, "songs": []})

    with pytest.raises(ValueError, match="不能当成空歌单"):
        asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).playlist_songs("88"))


@pytest.mark.parametrize("ids", ["bad", [{"id": True}], [{"id": -1}], [{"id": "1"}]])
def test_malformed_provider_ids_never_trigger_metadata_requests(ids: Any) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v6/playlist/detail"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "playlist": {
                    "id": 88,
                    "trackCount": 1,
                    "trackIds": ids,
                    "tracks": [],
                },
            },
        )

    with pytest.raises(ValueError):
        asyncio.run(NetEaseCatalog(httpx.MockTransport(respond)).playlist_songs("88"))


def test_old_endpoint_is_no_longer_allowed() -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("the retired endpoint must not be requested")

    with pytest.raises(ValueError, match="不支持"):
        asyncio.run(
            NetEaseCatalog(httpx.MockTransport(forbidden)).read_json(
                "https://music.163.com/api/playlist/detail", {"id": "88"}
            )
        )
