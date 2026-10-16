"""Private, fixed client operations; never accept model-authored JavaScript.

The official client's internal APIs are not stable. Python verifies the exact
observed function fingerprints before enabling mutations. These scripts never
open a URL, activate a window, synthesize input, or change playback mode.
"""

BOOTSTRAP = r"""(() => {
  const key = '__xinyu_music_cdp_v1';
  if (!window[key]) {
    if (!Array.isArray(window.webpackJsonp)) throw Error('unsupported_runtime');
    window.webpackJsonp.push([[key], {
      [key]: (module, exports, require) => { window[key] = {require, busy: false}; }
    }, [[key]]]);
  }
  const b = window[key], r = b.require;
  const exports = Object.values(r.c).map(x => x.exports).filter(Boolean);
  const values = [...new Set(exports.flatMap(x => Object.values(x)))];
  const stores = values.filter(
    x => x && x.inited && typeof x.getStore === 'function' &&
      typeof x.getDispatch === 'function'
  );
  if (stores.length !== 1) throw Error('unsupported_store');
  const a = stores[0], s = a.getStore();
  if (!s.playing || !s.playingList || !Array.isArray(s.playingList.curPlayingList))
    throw Error('unsupported_queue');
  const models = a.app._models;
  const effect = name => {
    const m = models.find(x => x.namespace === name.split('/')[0]);
    return m && m.effects && m.effects[name];
  };
  // Inspect loaded exports only: do not initialize arbitrary client modules.
  // Module numbers and minified export names differ even between adjacent releases.
  // Discover candidates without invoking them; Python verifies one complete profile.
  const functions = values.filter(x => typeof x === 'function');
  const formats = functions.filter(x => x.toString().includes('setPlayingItem'));
  const normalizers = functions.filter(x => {
    const text = x.toString();
    return text.length < 2000 && text.includes('isPlayedOnce') &&
      text.includes('randomOrder') && text.includes('resourceType') &&
      !text.includes('setPlayingItem');
  });
  const natives = [...new Set(exports.map(x => x.AudioPlayer).filter(Boolean))];
  const backends = exports.filter(x => x.p === 'playingList' && x.k &&
    x.k.Stop === 0 && x.k.Pause === 1 && x.k.Playing === 2 &&
    x.m && x.m.track === 'track');
  const normalize = normalizers[0], native = natives[0];
  const replace = effect('playingList/replaceCurPlayingList');
  const play = effect('playing/playOneTrackInPlayingList');
  const resume = effect('playing/resume');
  const checkPrivilege = effect('playing/checkPlayPrivilege');
  const setPlaying = effect('playing/setPlaying');
  const nativePlay = effect('playing/nativePlay');
  if (formats.length !== 1 || normalizers.length !== 1 || natives.length !== 1 ||
      ![normalize, replace, play, resume, native.subscribePlayStatus,
        checkPrivilege, setPlaying, nativePlay]
        .every(x => typeof x === 'function'))
    throw Error('unsupported_operations');
  if (backends.length !== 1) throw Error('unsupported_queue_backend');
  b.store = a; b.format = formats[0]; b.normalize = normalize; b.native = native;
  b.signature = list => JSON.stringify(list.map(x => [
    String(x.resourceId), x.displayOrder, x.randomOrder
  ]));
  b.read = () => {
    const s = a.getStore(), p = s.playing, item = p.curPlaying, t = item && item.track || {};
    const progress = b.progress, now = Date.now();
    const nativeReady = item && !p.isLoadingFirst &&
      String(p.resourceTrackId) === String(item.resourceId);
    const timing = nativeReady && progress && progress.playId === p.playId &&
      Number.isFinite(progress.current) && progress.current >= 0 &&
      (p.playingState !== 2 || now - progress.seen <= 3000) ? {
        position_ms:Math.round(progress.current*1000),sampled_at_ms:progress.seen,
        duration_ms:Math.round(p.resourceDuration*1000),timeline_source:'netease_native_cdp'
      } : {};
    // These are the client's actual playback flags, never inferred from fee/VIP tags.
    let access = 'unknown';
    if (nativeReady && 'position_ms' in timing &&
        typeof p.resourceIsTryType === 'boolean' &&
        typeof p.resourceIsFullTryType === 'boolean') {
      access = p.resourceIsTryType ? 'preview' :
        p.resourceIsFullTryType ? 'full_trial' : 'full';
    }
    const trial = p.freeTrialInfo;
    const bounds = access === 'preview' && trial &&
      Number.isFinite(trial.start) && Number.isFinite(trial.end) &&
      trial.start >= 0 && trial.end > trial.start ? {
        preview_start_ms:Math.round(trial.start*1000),
        preview_end_ms:Math.round(trial.end*1000)
      } : {};
    return {song_id: item ? String(item.resourceId) : '',
      title: String(t.name || ''),
      playback: {0:'stopped',1:'paused',2:'playing'}[p.playingState] || 'unknown',
      artist:(t.artists || []).map(x=>x.name).filter(Boolean).join('/'),
      album:String((t.album || {}).name || ''),...timing,
      playback_access:access,...bounds,
      mode: p.playingMode, queue_count: s.playingList.curPlayingList.length,
      queue_signature: b.signature(s.playingList.curPlayingList),
      anonymous: Boolean(s.host.isAnonymous)};
  };
  return {proof: {formatter: b.format.toString(), normalizer: normalize.toString(),
    replace: replace.toString(), play: play.toString(), resume:resume.toString(),
    subscribe:native.subscribePlayStatus.toString(),
    checkPrivilege:checkPrivilege.toString(), setPlaying:setPlaying.toString(),
    nativePlay:nativePlay.toString()}, state: b.read()};
})()"""

READ_STATE = "window.__xinyu_music_cdp_v1.read()"

WATCH_PROGRESS = r"""(async () => {
  const b = window.__xinyu_music_cdp_v1;
  if (!b.progressSubscribed) {
    b.progressSubscribed = true;
    try {
      await b.native.subscribePlayStatus({type:'playprogress',callback:p=>{
        b.progress={playId:p.playId,current:p.current,seen:Date.now()};
      }});
    } catch (_) { b.progressSubscribed=false; throw Error('progress_unavailable'); }
  }
  return true;
})()"""

# __REQUEST__ is one JSON object containing a canonical numeric ID and bounded
# metadata from the fixed NetEase song-detail endpoint, never executable text.
PLAY = r"""(async () => {
  const b = window.__xinyu_music_cdp_v1, request = JSON.parse(__REQUEST__);
  if (b.busy) return {status:'failed', reason:'background_busy', dispatched:false};
  b.busy = true;
  let dispatched = false;
  try {
    const a = b.store, s = a.getStore(), p = s.playing;
    const queue = s.playingList.curPlayingList;
    if (s.host.isAnonymous) return {status:'failed', reason:'login_required', dispatched:false};
    if (!['playOrder','playCycle','playOneCycle','playRandom'].includes(p.playingMode))
      return {status:'failed', reason:'unsupported_play_mode', dispatched:false};
    const mode = p.playingMode, before = b.signature(queue);
    const matches = queue.filter(x => String(x.resourceId) === request.song_id);
    if (matches.length > 1)
      return {status:'failed', reason:'ambiguous_queue_item', dispatched:false};
    let item = matches[0], appended = false, expected = before;
    if (item && item.resourceType !== 'track')
      return {status:'failed', reason:'unsupported_resource', dispatched:false};
    const track = item ? item.track : request.track;
    if (!track || String(track.id) !== request.song_id)
      return {status:'failed', reason:'invalid_song_detail', dispatched:false};
    // Fee/status labels are not playback entitlement. Let the official client
    // perform its ordinary permission checks and offer its authorized preview.
    // Do not alter privilege flags, request an unrestricted stream, or buy anything.
    if (!item) {
      if (queue.length >= 10000)
        return {status:'failed', reason:'queue_full', dispatched:false};
      const from = {text:'心隅',href:'',resourceType:'track',scene:'search',fromInfo:{
        originalScene:'search',originalResourceType:'track',computeSourceResourceType:'track',sourceData:{}}};
      const formatted = b.format(track, {scene:'search',trackFrom:from,playId:track.id,
        playingMode:mode,setPlayingItem:()=>{},getPlayingItem:()=>null,
        referInfo:{addrefer:'',multirefers:[]}});
      if (!formatted) return {status:'failed', reason:'invalid_song_detail', dispatched:false};
      item = b.normalize(formatted)[0];
      item.displayOrder = queue.reduce((n,x)=>Math.max(n,x.displayOrder),-1) + 1;
      item.randomOrder = queue.reduce((n,x)=>Math.max(n,x.randomOrder),-1) + 1;
      if (!Number.isSafeInteger(item.displayOrder) || !Number.isSafeInteger(item.randomOrder))
        return {status:'failed', reason:'unsupported_queue_order', dispatched:false};
      expected = JSON.stringify([...JSON.parse(before),
        [String(item.resourceId),item.displayOrder,item.randomOrder]]);
      // The normal addItemToCurPlayingList action reshuffles every existing item.
      // Persist an append made from the existing objects; never clear/rebuild them.
      dispatched = true;
      await a.getDispatch()({type:'playingList/replaceCurPlayingList',payload:{
        list:[...queue,item]}});
      appended = true;
    }
    let current = b.read();
    if (current.queue_signature !== expected || current.mode !== mode)
      return {status:dispatched?'uncertain':'failed',reason:'queue_changed',dispatched};
    if (current.song_id !== request.song_id || current.playback !== 'playing') {
      dispatched = true;
      // Use the client's ordinary privilege checks and queue selection. No webmsg.
      if (current.song_id === request.song_id && current.playback === 'paused') {
        await a.getDispatch()({type:'playing/resume',payload:{triggerScene:'playingList'}});
      } else {
        await a.getDispatch()({type:'playing/playOneTrackInPlayingList',payload:{
          item,switchType:'call',flag:0,triggerScene:'playingList',triggerAction:'play'}});
      }
    }
    current = b.read();
    return {status:'requested',dispatched,appended,queue_signature:expected,mode,
      queue_preserved:current.queue_signature===expected && current.mode===mode};
  } catch (_) {
    return {status:dispatched?'uncertain':'failed',reason:'client_operation_failed',dispatched};
  } finally { b.busy = false; }
})()"""
