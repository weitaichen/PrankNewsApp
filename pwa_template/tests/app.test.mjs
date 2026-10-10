import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { setImmediate } from 'node:timers/promises';

const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const episode = JSON.parse(await readFile(new URL('../episode.json', import.meta.url), 'utf8'));

function playerHarness({ available = true, unsupportedActions = false,
  offlineReady = null, networkAvailable = available, slowWorker = false,
  workerEpisode = null, clipboard = null } = {}) {
  const elements = new Map();
  function element(id) {
    const listeners = new Map();
    const attributes = new Map();
    return {
      id, value: '0', textContent: '', hidden: false, disabled: true,
      style: { setProperty() {} },
      addEventListener(event, handler) {
        if (!listeners.has(event)) listeners.set(event, []);
        listeners.get(event).push(handler);
      },
      emit(event) { for (const handler of listeners.get(event) || []) handler(); },
      setAttribute(key, value) { attributes.set(key, value); },
      getAttribute(key) { return attributes.get(key); },
      removeAttribute(key) { attributes.delete(key); if (key === 'src') this.src = ''; },
      focus() { this.focused = true; },
      select() { this.selected = true; },
    };
  }
  const document = {
    title: '',
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element(id));
      return elements.get(id);
    },
  };
  const audio = document.getElementById('audio');
  Object.assign(audio, {
    src: '', duration: NaN, currentTime: 0, playbackRate: 1, paused: true, ended: false,
    load() {},
    async play() { this.paused = false; this.emit('play'); },
    pause() { this.paused = true; this.emit('pause'); },
  });
  const actions = new Map();
  const positions = [];
  const mediaSession = {
    setActionHandler(action, handler) {
      if (unsupportedActions) throw new Error('Unsupported');
      actions.set(action, handler);
    },
    setPositionState(position) { positions.push(position); },
  };
  // MessageChannel stub faithfully closes the page-side port after the reply.
  class Channel {
    constructor() {
      this.port1 = { close() {} };
      this.port2 = { postMessage: data => queueMicrotask(() => this.port1.onmessage({ data })) };
    }
  }
  let holdReplies = false;
  const held = [];
  const worker = { postMessage(message, ports) {
    const data = { audioAvailable: available, offlineReady: offlineReady ?? available,
      ...(workerEpisode ? { episode: workerEpisode } : {}) };
    const reply = () => ports[0].postMessage(data);
    if (holdReplies) held.push(reply);
    else reply();
  } };
  const workerListeners = new Map();
  let becomeReady;
  const workerReady = slowWorker ? new Promise(resolve => { becomeReady = resolve; }) : Promise.resolve({ active: worker });
  const navigator = {
    ...(clipboard ? { clipboard } : {}),
    mediaSession,
    serviceWorker: {
      async register() { return { active: slowWorker ? null : worker }; },
      ready: workerReady,
      addEventListener(type, listener) { workerListeners.set(type, listener); },
    },
  };
  class MediaMetadata { constructor(data) { Object.assign(this, data); } }
  const errors = [];
  const context = vm.createContext({
    document, navigator, window: { isSecureContext: true, MediaMetadata },
    MediaMetadata, MessageChannel: Channel, URL,
    location: { href: 'https://example.test/podcast/', origin: 'https://example.test' },
    setTimeout(callback, delay) { return setTimeout(callback, slowWorker && delay === 30000 ? 1 : delay); }, clearTimeout,
    console: { error(value) { errors.push(value); } },
    async fetch(url, options) {
      if (url === './episode.json') return Response.json(workerEpisode || episode);
      assert.equal(options.method, 'HEAD', 'fallback must not download the entire MP3');
      return new Response(null, { status: networkAvailable ? 200 : 404 });
    },
  });
  vm.runInContext(source, context);
  return {
    audio, actions, mediaSession, positions, errors,
    get: id => document.getElementById(id),
    setAvailable(value) { available = value; },
    activate(value = null) {
      if (value) workerEpisode = value;
      navigator.serviceWorker.controller = worker;
      becomeReady?.({ active: worker });
      workerListeners.get('controllerchange')?.();
    },
    resolveReadyOnly() { becomeReady?.({ active: worker }); },
    holdStatusReplies() { holdReplies = true; },
    replyToStatus(index = 0) { held.splice(index, 1)[0](); },
    async settle() { for (let count = 0; count < 20; count++) await setImmediate(); },
    async ready() {
      for (let attempt = 0; attempt < 20; attempt++) {
        await setImmediate();
        if (!document.getElementById('message').textContent.startsWith('正在')) return;
      }
      throw new Error('Player did not finish initialization.');
    },
  };
}

test('missing MP3 gives a friendly message without setting audio src or logging errors', async () => {
  const player = playerHarness({ available: false });
  await player.ready();
  assert.equal(player.get('play').disabled, true);
  assert.equal(player.audio.src, '');
  assert.match(player.get('message').textContent, /尚未上線/);
  assert.equal(player.get('offline-status').textContent, '');
  assert.equal(player.get('retry').hidden, false);
  assert.deepEqual(player.errors, []);
  player.setAvailable(true);
  player.get('retry').emit('click');
  await player.ready();
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3');
  assert.equal(player.get('play').disabled, false);
  assert.equal(player.get('offline-status').textContent, '已可離線收聽');
});

test('subscription controls are hidden without feedUrl', async () => {
  const player = playerHarness();
  await player.ready();
  assert.equal(player.get('podcast-subscription').hidden, true);
});

test('private feed opens Podcasts and copies the HTTPS subscription URL', async () => {
  const copied = [];
  const feedUrl = 'https://example.test/feed.xml';
  const player = playerHarness({ workerEpisode: { ...episode, feedUrl },
    clipboard: { async writeText(value) { copied.push(value); } } });
  await player.ready();
  assert.equal(player.get('podcast-subscription').hidden, false);
  assert.equal(player.get('podcast-listen').href, 'podcasts://example.test/feed.xml');
  assert.equal(player.get('feed-url').hidden, true);
  player.get('copy-feed').emit('click');
  await player.settle();
  assert.deepEqual(copied, [feedUrl]);
  assert.equal(player.get('feed-copy-status').textContent, '訂閱網址已複製。');
});

for (const clipboard of [null, { async writeText() { throw new Error('Denied'); } }]) {
  test(`clipboard ${clipboard ? 'rejection' : 'unavailable'} exposes selectable feed text`, async () => {
    const feedUrl = 'https://example.test/feed.xml';
    const player = playerHarness({ workerEpisode: { ...episode, feedUrl }, clipboard });
    await player.ready();
    player.get('copy-feed').emit('click');
    await player.settle();
    assert.equal(player.get('feed-url').hidden, false);
    assert.equal(player.get('feed-url').value, feedUrl);
    assert.equal(player.get('feed-url').focused, true);
    assert.equal(player.get('feed-url').selected, true);
  });
}

for (const feedUrl of ['http://example.test/feed.xml', 'https://user@example.test/feed.xml', 'javascript:alert(1)', 'invalid']) {
  test(`invalid subscription URL stays hidden: ${feedUrl}`, async () => {
    const player = playerHarness({ workerEpisode: { ...episode, feedUrl } });
    await player.ready();
    assert.equal(player.get('podcast-subscription').hidden, true);
    assert.equal(player.get('play').disabled, false);
  });
}

test('a custom page alias can subscribe to the fixed Vercel feed URL', async () => {
  const player = playerHarness({ workerEpisode: { ...episode, feedUrl: 'https://morning-news-fixed.vercel.app/feed.xml' } });
  await player.ready();
  assert.equal(player.get('podcast-subscription').hidden, false);
  assert.equal(player.get('podcast-listen').href, 'podcasts://morning-news-fixed.vercel.app/feed.xml');
});

test('public page has collapsed subscription help and neutral wording', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /在 Podcast 收聽/);
  assert.match(html, /<details>/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
  assert.match(html, /透過 URL 追蹤節目/);
  assert.doesNotMatch(html + source, /整人|假新聞|prank/i);
});

test('play, pause, progress, skip and Media Session share one audio element', async () => {
  const player = playerHarness();
  await player.ready();
  player.audio.duration = 100;
  player.audio.emit('loadedmetadata');
  assert.equal(player.get('duration').textContent, '1:40', 'real duration overrides JSON estimate');
  assert.equal(player.get('progress').disabled, false);
  assert.equal(player.mediaSession.metadata.title, episode.title);
  assert.equal(player.mediaSession.metadata.artist, episode.anchor);
  assert.equal(player.mediaSession.metadata.album, episode.show);
  assert.equal(player.mediaSession.metadata.artwork.length, 6);
  assert.deepEqual([...player.actions.keys()], ['play', 'pause', 'seekbackward', 'seekforward', 'seekto']);

  player.get('play').emit('click');
  await setImmediate();
  assert.equal(player.audio.paused, false);
  assert.equal(player.get('play').getAttribute('aria-label'), '暫停');
  assert.equal(player.mediaSession.playbackState, 'playing');
  player.get('play').emit('click');
  assert.equal(player.audio.paused, true);

  player.get('progress').value = '50';
  player.get('progress').emit('input');
  assert.equal(player.get('elapsed').textContent, '0:50');
  player.get('progress').emit('change');
  assert.equal(player.audio.currentTime, 50);
  player.get('backward').emit('click');
  assert.equal(player.audio.currentTime, 35);
  player.get('forward').emit('click');
  assert.equal(player.audio.currentTime, 65);
  player.actions.get('seekbackward')({ seekOffset: 10 });
  assert.equal(player.audio.currentTime, 55);
  player.actions.get('seekforward')({});
  assert.equal(player.audio.currentTime, 85);
  player.actions.get('seekto')({ seekTime: 1000 });
  assert.equal(player.audio.currentTime, 100);
  player.actions.get('seekto')({ seekTime: -1 });
  assert.equal(player.audio.currentTime, 0);
  await player.actions.get('play')();
  assert.equal(player.audio.paused, false);
  player.actions.get('pause')();
  assert.equal(player.audio.paused, true);
  assert.equal(player.positions.at(-1).duration, 100);
});

test('unsupported Media Session actions do not prevent page playback', async () => {
  const player = playerHarness({ unsupportedActions: true });
  await player.ready();
  player.get('play').emit('click');
  await setImmediate();
  assert.equal(player.audio.paused, false);
  assert.deepEqual(player.errors, []);
});

test('active worker quota failure still enables network streaming without offline badge', async () => {
  const player = playerHarness({ available: false, networkAvailable: true, offlineReady: false });
  await player.ready();
  assert.equal(player.get('play').disabled, false);
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3');
  assert.equal(player.get('offline-status').textContent, '目前無法離線儲存，請保持連線收聽');
  player.get('play').emit('click');
  await player.settle();
  assert.equal(player.audio.paused, false);
});

test('worker becoming ready after preparation timeout eventually shows offline badge', async () => {
  const player = playerHarness({ slowWorker: true, networkAvailable: true });
  await new Promise(resolve => setTimeout(resolve, 10));
  await player.settle();
  assert.equal(player.get('offline-status').textContent, '目前無法離線儲存，請保持連線收聽');
  player.activate();
  await player.settle();
  assert.equal(player.get('offline-status').textContent, '已可離線收聽');
});

test('controllerchange switches title and audio to the committed new build', async () => {
  const player = playerHarness();
  await player.ready();
  const next = { ...episode, title: '新的一集', audio: 'episode.mp3?v=new', cover: 'cover.png?v=new' };
  player.activate(next);
  await player.settle();
  assert.equal(player.get('episode-title').textContent, '新的一集');
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3?v=new');
  assert.equal(player.mediaSession.metadata.title, '新的一集');
});

test('late ready promise alone refreshes offline status without controllerchange', async () => {
  const player = playerHarness({ slowWorker: true, networkAvailable: true });
  await new Promise(resolve => setTimeout(resolve, 10));
  await player.settle();
  assert.notEqual(player.get('offline-status').textContent, '已可離線收聽');
  player.resolveReadyOnly();
  await player.settle();
  assert.equal(player.get('offline-status').textContent, '已可離線收聽');
});

test('metadata waits for matching audio status and late old replies cannot revert a new episode', async () => {
  const player = playerHarness();
  await player.ready();
  player.holdStatusReplies();
  const first = { ...episode, title: '版本 B', audio: 'episode.mp3?v=B' };
  const second = { ...episode, title: '版本 C', audio: 'episode.mp3?v=C' };
  player.activate(first);
  await player.settle();
  assert.equal(player.get('episode-title').textContent, episode.title);
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3');
  player.activate(second);
  await player.settle();
  player.replyToStatus(1);
  await player.settle();
  assert.equal(player.get('episode-title').textContent, '版本 C');
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3?v=C');
  player.replyToStatus(0);
  await player.settle();
  assert.equal(player.get('episode-title').textContent, '版本 C');
  assert.equal(player.audio.src, 'https://example.test/podcast/episode.mp3?v=C');
});
