import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../sw.js', import.meta.url), 'utf8');

function workerHarness({ audioStatus = 200, coverStatus = 200 } = {}) {
  // Use a subdirectory to verify paths work when the template isn't at /.
  const base = 'https://example.test/podcast/';
  const prefix = `news-podcast:${base}:`;
  const listeners = new Map();
  const stores = new Map([[`${prefix}old`, new Map()], ['unrelated-app', new Map()]]);
  const requests = [];
  let networkAvailable = true;
  let claimed = false;
  const data = {
    audio: 'episode.mp3', cover: 'cover.png', title: 'News',
  };
  const fetch = async (input, options) => {
    const url = typeof input === 'string' ? input : input.url;
    requests.push({ url, options });
    if (!networkAvailable) throw new Error('Offline');
    if (url.endsWith('episode.json')) return Response.json(data);
    if (url.endsWith('episode.mp3')) return new Response(Uint8Array.from({ length: 200 }, (_, i) => i), { status: audioStatus, headers: { 'Content-Type': 'audio/mpeg' } });
    if (url.endsWith('cover.png')) return new Response('cover', { status: coverStatus });
    return new Response('shell');
  };
  const caches = {
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        async match(url) { return store.get(url)?.clone(); },
        async put(url, response) {
          assert.notEqual(response.status, 206, 'partial audio must never be cached');
          store.set(url, response.clone());
        },
        async delete(url) { return store.delete(url); },
        async addAll(urls) {
          for (const url of urls) store.set(url, await fetch(url));
        },
      };
    },
  };
  const self = {
    registration: { scope: base }, location: { origin: 'https://example.test' },
    clients: { async claim() { claimed = true; } },
    async skipWaiting() {},
    addEventListener(type, callback) { listeners.set(type, callback); },
  };
  vm.runInNewContext(source, { self, caches, fetch, URL, Response, Headers });
  const dispatch = async (type, fields = {}) => {
    const pending = [];
    let result;
    listeners.get(type)({
      ...fields,
      waitUntil(promise) { pending.push(promise); },
      respondWith(promise) { result = promise; },
    });
    const response = await result;
    await Promise.all(pending);
    return response;
  };
  return {
    base, prefix, stores, requests, dispatch,
    get claimed() { return claimed; },
    goOffline() { networkAvailable = false; },
    setAudioStatus(status) { audioStatus = status; },
    async status(refresh = false) {
      let result;
      await dispatch('message', {
        data: { type: refresh ? 'CACHE_EPISODE' : 'GET_CACHE_STATUS' },
        ports: [{ postMessage(value) { result = value; } }],
      });
      return result;
    },
  };
}

test('install precaches configured assets, excludes tests, cleans only own old cache', async () => {
  const worker = workerHarness();
  await worker.dispatch('install');
  await worker.dispatch('activate');
  assert.equal(worker.claimed, true);
  assert.equal(worker.stores.has(`${worker.prefix}old`), false);
  assert.equal(worker.stores.has('unrelated-app'), true);
  assert.equal(worker.requests.some(({ url }) => url.includes('/tests/')), false);
  assert.equal((await worker.status()).offlineReady, true);
  worker.goOffline();
  const range = await worker.dispatch('fetch', { request: new Request(`${worker.base}episode.mp3`, { headers: { Range: 'bytes=0-1' } }) });
  assert.equal(range.status, 206);
  assert.equal(range.headers.get('Content-Range'), 'bytes 0-1/200');
  assert.deepEqual(new Uint8Array(await range.arrayBuffer()), new Uint8Array([0, 1]));
  const complete = await worker.dispatch('fetch', { request: new Request(`${worker.base}episode.mp3`) });
  assert.equal(complete.status, 200);
  assert.equal((await complete.arrayBuffer()).byteLength, 200);
  const page = await worker.dispatch('fetch', { request: new Request(`${worker.base}index.html`) });
  assert.equal(page.status, 200);
});

test('missing MP3 keeps shell usable and retry can complete the offline cache', async () => {
  const worker = workerHarness({ audioStatus: 404 });
  await worker.dispatch('install');
  assert.equal((await worker.status()).audioAvailable, false);
  assert.equal((await worker.status()).offlineReady, false);
  worker.setAudioStatus(200);
  assert.equal((await worker.status(true)).offlineReady, true);
  worker.goOffline();
  assert.equal((await worker.status(true)).offlineReady, true, 'offline refresh preserves complete cached media');
});

test('partial audio or missing cover cannot report offline ready', async () => {
  const partial = workerHarness({ audioStatus: 206 });
  await partial.dispatch('install');
  assert.equal((await partial.status()).offlineReady, false);
  assert.equal((await partial.status()).audioAvailable, false);
  const missingCover = workerHarness({ coverStatus: 404 });
  await missingCover.dispatch('install');
  assert.equal((await missingCover.status()).audioAvailable, true);
  assert.equal((await missingCover.status()).offlineReady, false);
});
