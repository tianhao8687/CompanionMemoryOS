"""Offline contracts for the fixed silent transport; no real player or account."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from companion_agent.automation.bundled_music import MUSIC_TOOLS, refresh_lyrics_catalog
from companion_agent.automation.models import MCPServerConfig, ToolRule
from companion_agent.integrations import netease as mcp
from companion_agent.integrations import netease_background as bg
from companion_agent.integrations import netease_cdp_channel as cdp
from companion_agent.integrations.netease_cdp_profiles import RUNTIME_PROFILES
from companion_agent.integrations.netease_cdp_scripts import BOOTSTRAP, PLAY, READ_STATE


def test_native_ownership_helpers_reject_non_windows_before_loading_dlls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cdp, "sys", SimpleNamespace(platform="linux"))
    with pytest.raises(cdp.BackgroundUnavailable, match="unsupported_platform"):
        cdp._listener_rows(2)
    with pytest.raises(cdp.BackgroundUnavailable, match="unsupported_platform"):
        cdp._process_path(123)
    with pytest.raises(cdp.BackgroundUnavailable, match="unsupported_platform"):
        cdp.LocalChannel(Path("cloudmusic.exe"))


@pytest.mark.parametrize(
    "address",
    [
        "ws://example.org:9223/devtools/page/abc",
        "ws://127.0.0.1:9224/devtools/page/abc",
        "ws://user@127.0.0.1:9223/devtools/page/abc",
        "ws://127.0.0.1:9223/devtools/page/abc?q=x",
        "ws://127.0.0.1:9223/devtools/page/abc#x",
        "wss://127.0.0.1:9223/devtools/page/abc",
        "ws://127.0.0.1:9223/devtools/browser/abc",
        "ws://127.0.0.1:9223/devtools/page/../abc",
    ],
)
def test_target_cannot_redirect_the_local_channel(address: str) -> None:
    with pytest.raises(cdp.BackgroundUnavailable):
        cdp.validate_target(
            [
                {
                    "type": "page",
                    "url": "orpheus://orpheus/pub/app.html",
                    "webSocketDebuggerUrl": address,
                }
            ]
        )


def test_main_target_must_be_unique() -> None:
    target = {
        "type": "page",
        "url": "orpheus://orpheus/pub/app.html",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/abc",
    }
    assert cdp.validate_target([target]) == target["webSocketDebuggerUrl"]
    for targets in [[], [target, target], [{**target, "url": "https://music.163.com"}]]:
        with pytest.raises(cdp.BackgroundUnavailable):
            cdp.validate_target(targets)


@pytest.mark.parametrize("version", tuple(RUNTIME_PROFILES))
def test_exact_four_reviewed_versions_can_negotiate(version: str) -> None:
    assert (
        cdp.client_version({"User-Agent": f"Mozilla/5.0 NeteaseMusicDesktop/{version}"}) == version
    )


@pytest.mark.parametrize(
    "agent",
    [
        None,
        "NeteaseMusicDesktop/3.1.41.000000",
        "NeteaseMusicDesktop/3.1.37.205318",
        "NeteaseMusicDesktop/3.1.42.999999",
        "NeteaseMusicDesktop/3.1.41.205529 other",
        "fakeNeteaseMusicDesktop/3.1.41.205529",
    ],
)
def test_unreviewed_build_never_passes_by_major_version(agent: Any) -> None:
    with pytest.raises(cdp.BackgroundUnavailable, match="unsupported_client_version"):
        cdp.client_version({"User-Agent": agent})


def test_runtime_fingerprints_must_match_one_whole_profile_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = {"play": "a", "normalize": "b"}
    changed = {"play": "c", "normalize": "d"}

    def digest(proof: dict[str, str]) -> dict[str, str]:
        return {key: hashlib.sha256(value.encode()).hexdigest() for key, value in proof.items()}

    monkeypatch.setattr(
        bg, "RUNTIME_PROFILES", {"v": {"base": digest(original), "hotfix": digest(changed)}}
    )
    value = {"proof": original, "state": {"anonymous": False}}
    assert bg.check_profile(value, "v")["runtime_profile"] == "base"
    assert bg.check_profile({**value, "proof": changed}, "v")["runtime_profile"] == "hotfix"
    for proof, version in [
        ({**original, "play": "c"}, "v"),
        (original, "other"),
        ({**original, "extra": "a"}, "v"),
        ({"play": "a"}, "v"),
    ]:
        with pytest.raises(cdp.BackgroundUnavailable, match="unsupported_client_runtime"):
            bg.check_profile({**value, "proof": proof}, version)


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([], "background_not_initialized"),
        ([("0.0.0.0", 9223, 1)], "nonlocal_listener"),
        ([("127.0.0.1", 9223, 1), ("::", 9223, 1)], "nonlocal_listener"),
        ([("127.0.0.1", 9223, 1), ("::1", 9223, 2)], "wrong_channel_owner"),
        ([("::1", 9223, 1)], "wrong_channel_owner"),
    ],
)
def test_listener_must_be_exclusively_loopback_and_single_owner(
    monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, int, int]], reason: str
) -> None:
    monkeypatch.setattr(cdp, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(cdp, "_listener_rows", lambda family: rows if family == 2 else [])
    with pytest.raises(cdp.BackgroundUnavailable, match=reason):
        cdp.channel_owner(Path("cloudmusic.exe"))


def test_listener_owner_must_match_installation_and_remain_the_same(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "cloudmusic.exe"
    monkeypatch.setattr(cdp, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        cdp, "_listener_rows", lambda family: [("127.0.0.1", 9223, 1)] if family == 2 else []
    )
    monkeypatch.setattr(cdp, "_process_path", lambda _: tmp_path / "other.exe")
    with pytest.raises(cdp.BackgroundUnavailable, match="wrong_channel_owner"):
        cdp.channel_owner(executable)
    monkeypatch.setattr(cdp, "_process_path", lambda _: executable)
    assert cdp.channel_owner(executable) == 1
    channel = object.__new__(cdp.LocalChannel)
    channel.executable, channel.pid = executable, 2
    with pytest.raises(cdp.BackgroundUnavailable, match="channel_changed"):
        channel.check_owner()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://example.org"}),
        httpx.Response(200, content=b"x" * 65537),
    ],
)
def test_discovery_rejects_redirects_and_oversized_payloads(response: httpx.Response) -> None:
    channel = object.__new__(cdp.LocalChannel)
    channel.deadline = time.monotonic() + 5
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client,
        pytest.raises(cdp.BackgroundUnavailable),
    ):
        channel._json(client, "/json/list")


def test_metadata_is_bounded_fixed_origin_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.Client
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url).startswith("https://music.163.com/api/song/detail?")
        return httpx.Response(302, headers={"Location": "https://example.org"})

    monkeypatch.setattr(
        bg.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(cdp.BackgroundUnavailable, match="invalid_song_detail"):
        bg.track_detail("123", deadline=time.monotonic() + 3)
    assert len(calls) == 1


class FakeChannel:
    def __init__(self, _: Path) -> None:
        self.version = "3.1.41.205529"
        self.deadline = time.monotonic() + 16
        self.calls: list[str] = []
        self.reads = 0
        self.closed = False
        self.raise_after_send = False
        self.valid_profile = True
        self.mode = "advance"
        self.access = "unknown"

    def evaluate(self, script: str, **_: object) -> Any:
        self.calls.append(script)
        if script == BOOTSTRAP:
            return {
                "proof": {"test": "known" if self.valid_profile else "changed"},
                "state": {"anonymous": False},
            }
        if script == READ_STATE:
            self.reads += 1
            return {
                "song_id": "999" if self.mode == "wrong_song" else "123",
                "playback": "playing",
                "queue_signature": "q",
                "mode": "playRandom",
                "position_ms": 1000 + (self.reads * 300 if self.mode != "stalled" else 0),
                "sampled_at_ms": int(time.time() * 1000),
                "title": "synthetic",
                "playback_access": self.access,
            }
        if "JSON.parse(" in script:
            if self.raise_after_send:
                raise TimeoutError("private details")
            return {
                "status": "requested",
                "queue_preserved": True,
                "queue_signature": "q",
                "mode": "playRandom",
                "appended": False,
            }
        return True

    def __enter__(self) -> FakeChannel:
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


def fake_backend(monkeypatch: pytest.MonkeyPatch) -> FakeChannel:
    channel = FakeChannel(Path("cloudmusic.exe"))
    monkeypatch.setattr(bg, "LocalChannel", lambda _: channel)
    monkeypatch.setattr(
        bg,
        "RUNTIME_PROFILES",
        {channel.version: {"test-profile": {"test": hashlib.sha256(b"known").hexdigest()}}},
    )
    monkeypatch.setattr(bg, "track_detail", lambda *a, **kw: {"id": 123, "fee": 0})
    return channel


def test_changed_profile_stops_before_any_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = fake_backend(monkeypatch)
    channel.valid_profile = False
    result = bg.BackgroundPlayer(Path("cloudmusic.exe")).play("123")
    assert result["reason"] == "unsupported_client_runtime"
    assert result["delivery"] == "not_sent" and channel.calls == [BOOTSTRAP] and channel.closed


def test_timeout_after_sending_does_not_resend_or_claim_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = fake_backend(monkeypatch)
    channel.raise_after_send = True
    result = bg.BackgroundPlayer(Path("cloudmusic.exe")).play("123")
    assert result["status"] == "uncertain" and result["playback_verified"] is False
    assert sum("JSON.parse(" in call for call in channel.calls) == 1 and channel.closed
    assert "private details" not in str(result)


@pytest.mark.parametrize(
    "mode,verified", [("advance", True), ("stalled", False), ("wrong_song", False)]
)
def test_only_actual_target_with_advancing_progress_confirms_playback(
    monkeypatch: pytest.MonkeyPatch, mode: str, verified: bool
) -> None:
    channel = fake_backend(monkeypatch)
    channel.mode = mode
    # Deterministic clock; no six-second real wait for deliberately stalled audio.
    clock = [100.0]
    monkeypatch.setattr(bg.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bg.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(bg.time, "time", lambda: clock[0])
    result = bg.BackgroundPlayer(Path("cloudmusic.exe")).play("123")
    assert result["playback_verified"] is verified
    assert result["status"] == ("succeeded" if verified else "uncertain")
    assert not {"queue_signature", "proof", "queue"}.intersection(result)
    assert not {"queue_signature", "proof", "queue"}.intersection(result.get("state", {}))


@pytest.mark.parametrize(
    "access,message",
    [
        ("full", "完整播放"),
        ("preview", "试听片段"),
        ("full_trial", "全曲试听"),
        ("unknown", "类型尚不明确"),
    ],
)
def test_verified_paid_playback_reports_client_access_instead_of_assuming_full(
    monkeypatch: pytest.MonkeyPatch,
    access: str,
    message: str,
) -> None:
    channel = fake_backend(monkeypatch)
    channel.access = access
    monkeypatch.setattr(bg, "track_detail", lambda *a, **kw: {"id": 123, "fee": 4})
    result = bg.BackgroundPlayer(Path("cloudmusic.exe")).play("123")
    assert result["playback_verified"] and result["state"]["playback_access"] == access
    assert message in result["message"]
    assert sum("JSON.parse(" in call for call in channel.calls) == 1


def test_trial_state_is_a_whitelist_not_an_account_or_stream_dump() -> None:
    state = {
        "song_id": "123",
        "playback_access": "preview",
        "preview_start_ms": 60000,
        "preview_end_ms": 90000,
        "freeTrialPrivilege": {"userId": "private"},
        "url": "private-stream",
        "cookie": "private",
    }
    result = bg.compact_state(state)
    assert result["preview_start_ms"] == 60000 and result["preview_end_ms"] == 90000
    assert "private" not in json.dumps(result)
    assert "preview_start_ms" not in bg.compact_state({**state, "playback_access": "full"})


BOOT_FIXTURE = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
let invoked=0;
const format=(track, {setPlayingItem}={})=>{invoked++;return track;};
const normalize=function(item){
 const {isPlayedOnce, randomOrder, resourceType}=item;invoked++;
 return [{isPlayedOnce,randomOrder,resourceType}];
};
const noop=()=>{invoked++;};
const playing={curPlaying:{resourceId:'123',track:{name:'synthetic',artists:[]}},
 playingState:2,playingMode:'playRandom',playId:'play-123',resourceTrackId:'123',
 isLoadingFirst:false,resourceDuration:200,resourceIsTryType:false,
 resourceIsFullTryType:false,...input.playing};
const state={playing,playingList:{curPlayingList:[]},host:{isAnonymous:false}};
const effects=Object.fromEntries(['resume','playOneTrackInPlayingList','checkPlayPrivilege',
 'setPlaying','nativePlay'].map(name=>['playing/'+name,noop]));
const store={inited:true,getStore:()=>state,getDispatch:()=>noop,
 app:{_models:[{namespace:'playing',effects}, {namespace:'playingList',
 effects:{'playingList/replaceCurPlayingList':noop}}]}};
const modules={};
modules[input.store]={exports:{a:store}};
modules[input.format]={exports:{b:format}};
modules[21]={exports:{[input.normalize]:normalize}};
modules[4]={exports:{AudioPlayer:Object.create({subscribePlayStatus:noop})}};
modules[input.enums]={exports:{p:'playingList',k:{Stop:0,Pause:1,Playing:2},m:{track:'track'}}};
if(input.ambiguous)modules[9999]={exports:{other:function(item){
 const {isPlayedOnce,randomOrder,resourceType}=item;return {isPlayedOnce,randomOrder,resourceType};
}}};
global.window={__xinyu_music_cdp_v1:{require:{c:modules},busy:false,
 progress:{playId:'play-123',current:60.3,seen:Date.now()}}};
try{
 const result=eval(input.script);
 console.log(JSON.stringify({state:result.state,proofKeys:Object.keys(result.proof),invoked}));
}catch(error){console.log(JSON.stringify({error:error.message,invoked}));}
"""


def execute_boot_fixture(**values: Any) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js required for private client-script fixtures")
    process = subprocess.run(
        [node, "-e", BOOT_FIXTURE],
        input=json.dumps(
            {"script": BOOTSTRAP, "store": 8, "format": 213, "enums": 7, "normalize": "u", **values}
        ),
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    return json.loads(process.stdout)


@pytest.mark.parametrize(
    "formatter,normalizer,enums",
    [(188, "s", 6), (192, "u", 6), (194, "u", 6), (212, "u", 7), (213, "u", 7)],
)
def test_bootstrap_handles_four_package_bindings_and_hotfix_without_calling_helpers(
    formatter: int,
    normalizer: str,
    enums: int,
) -> None:
    result = execute_boot_fixture(format=formatter, normalize=normalizer, enums=enums)
    assert "error" not in result and result["invoked"] == 0
    assert set(result["proofKeys"]) == set(next(iter(RUNTIME_PROFILES["3.1.38.205386"].values())))
    assert result["state"]["playback_access"] == "full"


@pytest.mark.parametrize(
    "playing,access,timing",
    [
        ({}, "full", True),
        ({"resourceIsTryType": True, "freeTrialInfo": {"start": 60, "end": 90}}, "preview", True),
        ({"resourceIsFullTryType": True}, "full_trial", True),
        ({"resourceIsTryType": None}, "unknown", True),
        ({"isLoadingFirst": True}, "unknown", False),
        ({"resourceTrackId": "999"}, "unknown", False),
        ({"playId": "previous-song"}, "unknown", False),
    ],
)
def test_native_access_is_bound_to_the_actual_loaded_track_and_progress(
    playing: dict[str, Any],
    access: str,
    timing: bool,
) -> None:
    state = execute_boot_fixture(playing=playing)["state"]
    assert state["playback_access"] == access
    assert ("position_ms" in state) is timing
    if access == "preview":
        assert state["preview_start_ms"] == 60000 and state["preview_end_ms"] == 90000


def test_ambiguous_runtime_discovery_fails_without_invoking_candidates() -> None:
    result = execute_boot_fixture(ambiguous=True)
    assert result == {"error": "unsupported_operations", "invoked": 0}


JS_FIXTURE = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const scenario=input.scenario, calls=[];
const original=[{id:'1',resourceId:'1',resourceType:'track',displayOrder:7,randomOrder:3,
  track:{id:1,fee:0,status:0},opaque:{keep:'unchanged'}},
 {id:'2',resourceId:'2',resourceType:'track',displayOrder:9,randomOrder:1,
  track:{id:2,fee:0,status:0}}];
const initial=JSON.stringify(original);
const state={host:{isAnonymous:false},playing:{playingMode:'playRandom',
  song_id:'1',playback:'playing'},playingList:{curPlayingList:original}};
const signature=q=>JSON.stringify(q.map(x=>[String(x.resourceId),x.displayOrder,x.randomOrder]));
const b={busy:false,signature,store:{getStore:()=>state,getDispatch:()=>async action=>{
 calls.push(action.type);
 if(action.type==='playingList/replaceCurPlayingList') {
   state.playingList.curPlayingList=action.payload.list;
   if(scenario==='concurrent')state.playingList.curPlayingList[0].randomOrder=88;
 } else if(action.type==='playing/resume')state.playing.playback='playing';
 else if(action.type==='playing/playOneTrackInPlayingList'){
   state.playing.song_id=action.payload.item.resourceId;state.playing.playback='playing';
 } else throw Error('unapproved action');
 }},format:track=>({resourceId:String(track.id),resourceType:'track',track}),
 normalize:item=>[item],read:()=>({...state.playing,
   mode:state.playing.playingMode,queue_signature:signature(state.playingList.curPlayingList)})};
global.window={__xinyu_music_cdp_v1:b};
global.pwned=false;
if(scenario==='paused')state.playing.playback='paused';
if(scenario==='special')state.playing.playingMode='playFm';
if(scenario==='busy')b.busy=true;
if(scenario==='full')state.playingList.curPlayingList=Array.from({length:10000},(_,i)=>({
 resourceId:String(i+10),displayOrder:i,randomOrder:i,track:{id:i+10,fee:0},resourceType:'track'}));
(async()=>{
 const result=await eval(input.script);
 console.log(JSON.stringify({result,calls,originalUnchanged:JSON.stringify(original)===initial,
  queue:state.playingList.curPlayingList.slice(0,3),mode:state.playing.playingMode,pwned}));
})().catch(error=>{console.error(error);process.exit(1)});
"""


@pytest.mark.parametrize(
    "scenario,identifier,fee,expected",
    [
        (
            "append",
            "3",
            0,
            ["playingList/replaceCurPlayingList", "playing/playOneTrackInPlayingList"],
        ),
        ("existing", "2", 0, ["playing/playOneTrackInPlayingList"]),
        ("noop", "1", 0, []),
        ("paused", "1", 0, ["playing/resume"]),
        (
            "paid",
            "3",
            1,
            ["playingList/replaceCurPlayingList", "playing/playOneTrackInPlayingList"],
        ),
        (
            "paid",
            "3",
            4,
            ["playingList/replaceCurPlayingList", "playing/playOneTrackInPlayingList"],
        ),
        (
            "paid",
            "3",
            16,
            ["playingList/replaceCurPlayingList", "playing/playOneTrackInPlayingList"],
        ),
        ("special", "3", 0, []),
        ("busy", "3", 0, []),
        ("full", "3", 0, []),
        ("concurrent", "3", 0, ["playingList/replaceCurPlayingList"]),
    ],
)
def test_fixed_script_preserves_queue_and_rejects_unsafe_states(
    scenario: str, identifier: str, fee: int, expected: list[str]
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js required to execute the private client-script fixture")
    request = json.dumps(
        {
            "song_id": identifier,
            "track": {
                "id": int(identifier),
                "fee": fee,
                "status": 0,
                "name": "');global.pwned=true;//\n</script>恶意标题",
            },
        },
        ensure_ascii=True,
    )
    script = PLAY.replace("__REQUEST__", json.dumps(request))
    process = subprocess.run(
        [node, "-e", JS_FIXTURE],
        input=json.dumps(
            {
                "scenario": scenario,
                "script": script,
            }
        ),
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    actual = json.loads(process.stdout)
    assert actual["calls"] == expected and actual["pwned"] is False
    if scenario not in {"special", "concurrent"}:
        assert actual["mode"] == "playRandom" and actual["originalUnchanged"]
    if scenario == "append":
        assert actual["queue"][2]["displayOrder"] == 10
        assert actual["queue"][2]["randomOrder"] == 4
        assert actual["result"]["queue_preserved"] is True
    if scenario == "concurrent":
        assert actual["result"]["reason"] == "queue_changed"
    if scenario in {"special", "busy", "full"}:
        assert actual["result"]["status"] == "failed"
        assert actual["result"]["dispatched"] is False


def test_mcp_state_uses_native_identity_with_system_controls_and_no_old_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp, "find_executable", lambda _: Path("cloudmusic.exe"))
    monkeypatch.setattr(
        mcp.BackgroundPlayer,
        "state",
        lambda _: {
            "available": True,
            "status": "succeeded",
            "song_id": "123",
            "title": "new",
            "controls": {"play": False},
        },
    )
    media = SimpleNamespace(
        state=AsyncMock(
            return_value={
                "available": True,
                "song_id": "old",
                "position_ms": 80000,
                "controls": {"play": True},
            }
        )
    )
    server = mcp.build_server(media=media)
    _, result = asyncio.run(server.call_tool("netease_playback_state", {}))
    assert result["song_id"] == "123" and result["controls"]["play"]
    assert "position_ms" not in result


@pytest.mark.parametrize(
    "native,current,refresh", [(False, False, True), (False, True, False), (True, False, False)]
)
def test_only_legacy_windows_catalog_refreshes_without_changing_permissions(
    native: bool, current: bool, refresh: bool
) -> None:
    server = MCPServerConfig(
        id="netease",
        label="Synthetic",
        enabled=True,
        **(
            {"transport": "native"}
            if native
            else {
                "command": "synthetic-python",
                "args": ["-m", "companion_agent.integrations.netease"],
            }
        ),
        tools={"netease_open_song": ToolRule(mode="off")},
    )
    catalog = [
        {
            "name": name,
            "description": "本机后台通道 playback_access" if current else "本机后台通道 付费不支持",
            "inputSchema": {"properties": {"search_type": {}}},
        }
        for name in MUSIC_TOOLS
    ]
    calls = []
    hub = SimpleNamespace(
        config=SimpleNamespace(servers=[server]),
        catalog={"netease": catalog},
        discover=calls.append,
    )
    before = server.model_dump()
    refresh_lyrics_catalog(hub, "synthetic-python")
    assert calls == (["netease"] if refresh else [])
    assert server.model_dump() == before
