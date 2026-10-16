"""Song cards are projections of scoped tool receipts, never model-authored commands."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from companion_agent.automation.hub import digest
from companion_agent.integrations.netease_catalog import song_id
from companion_agent.integrations.netease_lyrics import cover_url
from companion_agent.persona.models import PersonaModel
from companion_memoryos.schemas import ConversationRole, ConversationTurnRecord

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost
    from companion_agent.automation.hub import ToolHub


def tool_name(remote: str) -> str:
    return f"mcp_netease_{digest(remote)[:12]}"


SEARCH = tool_name("netease_search_songs")
OPEN = tool_name("netease_open_song")
STATE = tool_name("netease_playback_state")


def require_lyric_match(
    hub: ToolHub, arguments: dict[str, Any], conversation: str, request_id: str
) -> None:
    """An AI-selected result must have evidence; a separate explicit card click can choose it."""
    with hub.store.database.connection() as db:
        rows = db.execute(
            "SELECT arguments, result FROM agent_actions WHERE conversation_id=? AND request_id=? "
            "AND tool_name=? AND status='succeeded' ORDER BY rowid DESC",
            (conversation, request_id, SEARCH),
        ).fetchall()
    import json

    lyrics = [row for row in rows if json.loads(row["arguments"]).get("search_type") == "lyrics"]
    if not lyrics:
        return
    matched = any(
        song["id"] == arguments.get("song_id") and song["lyric_match"]
        for row in lyrics
        for song in songs_from(json.loads(row["result"]))
    )
    if not matched:
        raise ValueError("还没核实这首歌包含用户给出的歌词，请补充歌词或让用户点选候选歌曲。")


class MusicPickInput(PersonaModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    search_action_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    song_id: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    request_id: str = Field(min_length=1, max_length=80)


def songs_from(result: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    data = result.get("data", {})
    if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
        return []
    songs = []
    for raw in data["songs"][:limit]:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            continue
        try:
            identifier = song_id(raw.get("id", ""))
        except ValueError:
            continue
        artists = raw.get("artists")
        songs.append(
            {
                "id": identifier,
                "name": raw["name"][:200],
                "artists": [a[:100] for a in artists[:10] if isinstance(a, str)]
                if isinstance(artists, list)
                else [],
                "album": str(raw.get("album", ""))[:200],
                "cover_url": cover_url(raw.get("cover_url")),
                "lyric_match": raw.get("lyric_match") is True,
            }
        )
    return songs


def playback_receipt(song: dict[str, Any], media: dict[str, Any]) -> str:
    if media.get("available") is not True or media.get("playback") != "playing":
        return "requested"
    if media.get("song_id"):
        return "verified" if str(media["song_id"]) == song["id"] else "requested"
    # A title alone cannot distinguish a cover/live version or a different recording.
    if (
        song["album"]
        and len(song["artists"]) == 1
        and media.get("title") == song["name"]
        and media.get("artist") == song["artists"][0]
        and media.get("album") == song["album"]
    ):
        return "metadata_matched"
    return "requested"


def request_receipt(song: dict[str, Any], media: dict[str, Any]) -> str:
    state = playback_receipt(song, media)
    confirmation = media.get("confirmation", {})
    if (
        state == "requested"
        and isinstance(confirmation, dict)
        and confirmation.get("song_id") == song["id"]
        and confirmation.get("state") in {"paused", "not_started", "unverified"}
    ):
        return str(confirmation["state"])
    return state


class MusicRequests:
    def __init__(self, host: RomanceHost) -> None:
        self.host = host

    def observe(self, conversation: str, media: dict[str, Any]) -> bool:
        """Attach late positive evidence to the latest request, without any I/O to the player."""
        if media.get("available") is not True or media.get("playback") != "playing":
            return False
        with self.host.database.atomic() as db:
            row = db.execute(
                "SELECT * FROM agent_actions WHERE conversation_id=? AND tool_name=? "
                "ORDER BY rowid DESC LIMIT 1",
                (conversation, OPEN),
            ).fetchone()
            if row is None or row["status"] != "succeeded":
                return False
            attempt = self.host.tools.store.action_dict(dict(row))
            if (
                attempt["result"].get("playback_confirmation")
                or not 0
                <= (
                    datetime.now(UTC) - datetime.fromisoformat(attempt["updated_at"])
                ).total_seconds()
                <= 120
            ):
                return False
            request = attempt["request_id"]
            if request.startswith("music_card:"):
                search_id = request.split(":", 2)[1]
            else:
                search_row = db.execute(
                    "SELECT id FROM agent_actions WHERE conversation_id=? AND request_id=? "
                    "AND tool_name=? AND status='succeeded' ORDER BY rowid DESC LIMIT 1",
                    (conversation, request, SEARCH),
                ).fetchone()
                if search_row is None:
                    return False
                search_id = search_row["id"]
            try:
                search = self._search(search_id, conversation)
            except ValueError:
                return False
            song = next(
                (
                    s
                    for s in songs_from(search["result"])
                    if s["id"] == attempt["arguments"].get("song_id")
                ),
                None,
            )
            if song is None or (state := playback_receipt(song, media)) == "requested":
                return False
            evidence = {
                "state": state,
                "song_id": song["id"],
                "observed_at": datetime.now(UTC).isoformat(),
                "source": "media_poll",
            }
            db.execute(
                "UPDATE agent_actions SET result=? WHERE id=?",
                (
                    json.dumps(
                        {**attempt["result"], "playback_confirmation": evidence}, ensure_ascii=False
                    ),
                    attempt["id"],
                ),
            )
            return True

    def _search(self, action_id: str, conversation: str) -> dict[str, Any]:
        self.host.journal.require_storage()
        self.host.scope(conversation)
        with self.host.database.connection() as db:
            row = db.execute(
                "SELECT * FROM agent_actions WHERE id=? AND conversation_id=? "
                "AND tool_name=? AND status='succeeded'",
                (action_id, conversation, SEARCH),
            ).fetchone()
            source = db.execute(
                "SELECT id FROM conversation_turns WHERE user_id=? AND conversation_id=? "
                "AND idempotency_key=? AND role='user'",
                (self.host.key.user_id, conversation, row["request_id"] if row else ""),
            ).fetchone()
        if row is None or source is None:
            raise ValueError("这次找歌记录已不可用，请重新找歌。")
        self.host.journal.require_turn(source["id"], conversation)
        return self.host.tools.store.action_dict(dict(row))

    def cards(self, turn: ConversationTurnRecord) -> list[dict[str, Any]]:
        if turn.role is not ConversationRole.ASSISTANT or not turn.reply_to_turn_id:
            return []
        conversation = turn.scope.conversation_id or ""
        try:
            self.host.journal.require_turn(turn.id, conversation)
            source = self.host.journal.require_turn(turn.reply_to_turn_id, conversation)
            with self.host.database.connection() as db:
                row = db.execute(
                    "SELECT id FROM agent_actions WHERE conversation_id=? AND request_id=? "
                    "AND tool_name=? AND status='succeeded' ORDER BY rowid DESC LIMIT 1",
                    (conversation, source.idempotency_key, SEARCH),
                ).fetchone()
            if row is None:
                return []
            search = self._search(row["id"], conversation)
        except ValueError:
            return []
        with self.host.database.connection() as db:
            rows = db.execute(
                "SELECT * FROM agent_actions WHERE conversation_id=? "
                "AND (request_id=? OR request_id LIKE ?) ORDER BY rowid",
                (conversation, source.idempotency_key, f"music_card:{search['id']}:%"),
            ).fetchall()
        actions = [self.host.tools.store.action_dict(dict(row)) for row in rows]
        songs = songs_from(search["result"])
        # Keep an explicitly chosen result visible even when it was beyond the first three.
        opened = [a["arguments"].get("song_id") for a in actions if a["tool_name"] == OPEN]
        if opened:
            songs.sort(key=lambda song: song["id"] != opened[-1])
        comfort = any(a["tool_name"] == "app_comfort_music" for a in actions)
        if comfort:
            # Companionship is one selected song, not another list of decisions.
            songs = [s for s in songs if opened and s["id"] == opened[-1]][:1]
        cards = []
        for song in songs[:3]:
            state, pending = "candidate", None
            attempts = [
                a
                for a in actions
                if a["tool_name"] == OPEN and a["arguments"].get("song_id") == song["id"]
            ]
            if attempts:
                attempt = attempts[-1]
                state = attempt["status"]
                if state == "pending":
                    pending = attempt["id"]
                if state == "succeeded":
                    state = "requested"
                    observations = [
                        a
                        for a in actions
                        if a["tool_name"] == STATE
                        and a["status"] == "succeeded"
                        and a["request_id"] == attempt["request_id"]
                        and a["created_at"] >= attempt["created_at"]
                    ]
                    if observations:
                        media = observations[-1]["result"].get("data", {})
                        if isinstance(media, dict):
                            state = request_receipt(song, media)
                    evidence = attempt["result"].get("playback_confirmation", {})
                    if (
                        isinstance(evidence, dict)
                        and evidence.get("song_id") == song["id"]
                        and evidence.get("state") in {"verified", "metadata_matched"}
                    ):
                        state = evidence["state"]
                    if (
                        state == "requested"
                        and (
                            datetime.now(UTC) - datetime.fromisoformat(attempt["updated_at"])
                        ).total_seconds()
                        > 15
                    ):
                        state = "unverified"
            cards.append(
                {
                    **song,
                    "comfort": comfort,
                    "search_action_id": search["id"],
                    "state": state,
                    "pending_action_id": pending,
                }
            )
        return cards

    def pick(self, item: MusicPickInput) -> dict[str, Any]:
        with self.host.exclusive(), self.host.tools.lock:
            search = self._search(item.search_action_id, item.conversation_id)
            song = next((s for s in songs_from(search["result"]) if s["id"] == item.song_id), None)
            if song is None:
                raise ValueError("这首歌不在本次搜索结果中，请重新找歌。")
            key = f"music_card:{item.search_action_id}:{item.request_id}"
            args = {"song_id": item.song_id}
            self.host.music._binding("netease_open_song", args)
            result = self.host.tools.invoke(OPEN, args, item.conversation_id, key)
            # This authenticated click authorizes this one selected song, not future AI calls.
            if result["status"] == "pending":
                result = self.host.tools.approve(result["action_id"], True)
            state = result["status"]
            if state == "succeeded":
                state = "requested"
                try:
                    self.host.music._binding("netease_playback_state", {})
                    observation = self.host.tools.invoke(STATE, {}, item.conversation_id, key)
                    if observation["status"] == "pending":
                        observation = self.host.tools.approve(observation["action_id"], True)
                    media = observation.get("data", {})
                    if observation["status"] == "succeeded" and isinstance(media, dict):
                        state = request_receipt(song, media)
                except ValueError:
                    pass  # Opening is still only requested when the state permission is off.
            return {"operation": result, "state": state, "song_id": item.song_id}
