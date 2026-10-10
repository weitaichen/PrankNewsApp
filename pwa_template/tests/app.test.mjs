import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { setImmediate } from 'node:timers/promises';

const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const episode = JSON.parse(await readFile(new URL('../episode.json', import.meta.url), 'utf8'));

function playerHarness({ available = true, unsupportedActions = false } = {}) {
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
  const worker = { postMessage(message, ports) { ports[0].postMessage({ audioAvailable: available, offlineReady: available }); } };
  const navigator = {
    mediaSession,
    serviceWorker: { async register() {}, ready: Promise.resolve({ active: worker }) },
  };
  class MediaMetadata { constructor(data) { Object.assign(this, data); } }
  const errors = [];
  const context = vm.createContext({
    document, navigator, window: { isSecureContext: true, MediaMetadata },
    MediaMetadata, MessageChannel: Channel, URL,
    location: { href: 'https://example.test/podcast/', origin: 'https://example.test' },
    setTimeout, clearTimeout,
    console: { error(value) { errors.push(value); } },
    async fetch(url) {
      assert.equal(url, './episode.json', 'missing audio must never be fetched by the page');
      return Response.json(episode);
    },
  });
  vm.runInContext(source, context);
  return {
    audio, actions, mediaSession, positions, errors,
    get: id => document.getElementById(id),
    setAvailable(value) { available = value; },
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
