import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../sw.js', import.meta.url), 'utf8');

function workerHarness({ audioStatus = 200, coverStatus = 200, version = '__BUILD_ID__',
  sharedStores, quotaAudio = false, failAudio = false, interruptAudio = false } = {}) {
  // Use a subdirectory to verify paths work when the template isn't at /.
  const base = 'https://example.test/podcast/';
  const prefix = `news-podcast:${base}:`;
  const listeners = new Map();
  const stores = sharedStores || new Map([[`${prefix}old`, new Map()], ['unrelated-app', new Map()]]);
  const requests = [];
  let networkAvailable = true;
  let claimed = false;
  let skipped = false;
  const data = {
    audio: version === '__BUILD_ID__' ? 'episode.mp3' : `episode.mp3?v=${version}`,
    cover: version === '__BUILD_ID__' ? 'cover.png' : `cover.png?v=${version}`,
    title: version, buildId: version,
  };
  const fetch = async (input, options) => {
    const url = typeof input === 'string' ? input : input.url;
    requests.push({ url, options });
    if (!networkAvailable) throw new Error('Offline');
    const path = new URL(url).pathname;
    if (path.endsWith('episode.json')) return Response.json(data);
    if (path.endsWith('episode.mp3')) {
      if (failAudio) throw new Error('Interrupted download');
      if (interruptAudio) return new Response(new ReadableStream({
        start(controller) { controller.error(new Error('Body interrupted after HTTP 200')); },
      }));
      return new Response(Uint8Array.from({ length: 200 }, (_, i) => version === 'B' ? 200 - i : i), { status: audioStatus, headers: { 'Content-Type': 'audio/mpeg' } });
    }
    if (path.endsWith('cover.png')) return new Response('cover', { status: coverStatus });
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
          if (quotaAudio && new URL(url).pathname.endsWith('episode.mp3')) throw new Error('QuotaExceededError');
          await response.clone().arrayBuffer(); // Real Cache.put waits for the complete body.
          store.set(url, response.clone());
        },
        async delete(url) { return store.delete(url); },
        async addAll(urls) {
          for (const request of urls) {
            assert.equal(request.cache, 'reload');
            store.set(request.url, await fetch(request));
          }
        },
      };
    },
  };
  const self = {
    registration: { scope: base }, location: { origin: 'https://example.test' },
    clients: { async claim() { claimed = true; } },
    async skipWaiting() { skipped = true; },
    addEventListener(type, callback) { listeners.set(type, callback); },
  };
  vm.runInNewContext(source.replace("'__BUILD_ID__'", `'${version}'`), { self, caches, fetch, URL, Request, Response, Headers });
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
    get skipped() { return skipped; },
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

test('each build gets its own cache and a complete update switches metadata and MP3 together', async () => {
  const old = workerHarness({ version: 'A' });
  await old.dispatch('install');
  await old.dispatch('activate');
  const next = workerHarness({ version: 'B', sharedStores: old.stores });
  await next.dispatch('install');
  assert.equal(next.skipped, true);
  assert.equal(old.stores.has(`${old.prefix}A`), true, 'old cache survives until activation');
  await next.dispatch('activate');
  assert.equal(old.stores.has(`${old.prefix}A`), false);
  next.goOffline();
  const json = await next.dispatch('fetch', { request: new Request(`${next.base}episode.json`) });
  assert.equal((await json.json()).title, 'B');
  const audio = await next.dispatch('fetch', { request: new Request(`${next.base}episode.mp3?v=B`) });
  assert.equal(new Uint8Array(await audio.arrayBuffer())[0], 200);
  assert.equal((await next.status()).offlineReady, true);
});

for (const failure of [{ audioStatus: 500 }, { audioStatus: 404 }, { failAudio: true },
  { interruptAudio: true }, { quotaAudio: true }, { coverStatus: 500 }]) {
  test(`incomplete update preserves old episode and refuses activation: ${JSON.stringify(failure)}`, async () => {
    const old = workerHarness({ version: 'A' });
    await old.dispatch('install');
    await old.dispatch('activate');
    const next = workerHarness({ version: 'B', sharedStores: old.stores, ...failure });
    await assert.rejects(next.dispatch('install'), /not fully cached/);
    assert.equal(next.skipped, false);
    assert.equal((await next.status()).offlineReady, false);
    const incomplete = old.stores.get(`${old.prefix}B`);
    assert.equal(incomplete.has(`${old.base}episode.json`), false, 'JSON only commits after both assets');
    old.goOffline();
    const json = await old.dispatch('fetch', { request: new Request(`${old.base}episode.json`) });
    assert.equal((await json.json()).title, 'A');
    const audio = await old.dispatch('fetch', { request: new Request(`${old.base}episode.mp3?v=A`) });
    assert.equal(new Uint8Array(await audio.arrayBuffer())[0], 0);
  });
}

test('quota failure on first install allows streaming but never reports offline ready', async () => {
  const worker = workerHarness({ quotaAudio: true });
  await worker.dispatch('install');
  await worker.dispatch('activate');
  const status = await worker.status();
  assert.equal(status.audioAvailable, true);
  assert.equal(status.offlineReady, false);
  const audio = await worker.dispatch('fetch', { request: new Request(`${worker.base}episode.mp3`) });
  assert.equal(audio.status, 200);
  assert.equal((await audio.arrayBuffer()).byteLength, 200);
  worker.goOffline();
  assert.equal((await worker.status()).audioAvailable, false);
});

test('old worker refresh keeps committed metadata immutable while a new build installs', async () => {
  const worker = workerHarness({ version: 'A' });
  await worker.dispatch('install');
  const requests = worker.requests.length;
  assert.equal((await worker.status(true)).episode.title, 'A');
  assert.equal(worker.requests.length, requests, 'refresh never overwrites an immutable build');
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
