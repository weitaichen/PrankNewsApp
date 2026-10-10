'use strict';

/**
 * Pure, independently testable transformation. Never consumes the caller's
 * response or reads cache/network/global worker state. Single byte ranges only;
 * unsupported multipart/unit syntax is ignored with a full 200 response.
 */
async function buildRangeResponse(fullResponse, rangeHeader) {
  const bytes = await fullResponse.clone().arrayBuffer();
  const size = bytes.byteLength;
  const headers = new Headers(fullResponse.headers);
  // Fetch bodies are decoded; inherited compression/length headers may be stale.
  headers.delete('Content-Encoding');
  headers.delete('Content-Range');
  headers.set('Accept-Ranges', 'bytes');
  headers.set('Content-Length', String(size));

  const full = () => new Response(bytes, { status: 200, headers });
  if (!rangeHeader) return full();
  const match = /^bytes=(\d*)-(\d*)$/i.exec(rangeHeader.trim());
  if (!match) return full();

  const unsatisfiable = () => {
    headers.set('Content-Range', `bytes */${size}`);
    headers.set('Content-Length', '0');
    return new Response(null, { status: 416, headers });
  };
  if (!size || (!match[1] && !match[2])) return unsatisfiable();

  let start;
  let end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return unsatisfiable();
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= size || end < start) return unsatisfiable();
    end = Math.min(end, size - 1);
  }

  headers.set('Content-Range', `bytes ${start}-${end}/${size}`);
  headers.set('Content-Length', String(end - start + 1));
  return new Response(bytes.slice(start, end + 1), { status: 206, headers });
}

// A classic worker needs no imports. The guard also allows Node vm unit tests.
if (typeof self !== 'undefined' && typeof self.addEventListener === 'function') {
  // The literal placeholder also serves as a usable version in the raw template.
  const CACHE_VERSION = '__BUILD_ID__';
  const BASE = self.registration.scope;
  const CACHE_PREFIX = `news-podcast:${BASE}:`;
  const CACHE_NAME = `${CACHE_PREFIX}${CACHE_VERSION}`;
  const urlFor = path => new URL(path, BASE).href;
  const SHELL = [
    './', './index.html', './app.js', './style.css', './sw.js', './manifest.json',
    './icon-192.png', './icon-512.png', './apple-touch-icon.png',
  ].map(urlFor);
  const EPISODE_URL = urlFor('./episode.json');
  let refreshPromise;
  let networkEpisode;

  function mediaURLs(episode) {
    return ['audio', 'cover'].map(key => {
      if (typeof episode[key] !== 'string' || !episode[key].trim()) throw new Error('Missing media path.');
      const url = new URL(episode[key], BASE);
      if (url.origin !== self.location.origin || !['http:', 'https:'].includes(url.protocol)) throw new Error('Media must be same-origin.');
      return url.href;
    });
  }

  async function cachedEpisode(cache) {
    const response = await cache.match(EPISODE_URL);
    return response ? response.json() : null;
  }

  async function cacheEpisode() {
    const cache = await caches.open(CACHE_NAME);
    // A build is immutable. Never refresh an old worker with a newer build's JSON.
    if (await cachedEpisode(cache)) return true;
    try {
      const response = await fetch(EPISODE_URL, { cache: 'no-store' });
      if (response.status !== 200) throw new Error('Episode unavailable.');
      const episode = await response.clone().json();
      if (episode.buildId && episode.buildId !== CACHE_VERSION) throw new Error('Build changed during installation.');
      const urls = mediaURLs(episode);
      networkEpisode = episode;
      // Fetch full bodies before committing metadata. Unique per-build caches
      // and versioned media URLs ensure partial writes never replace old audio.
      const media = await Promise.all(urls.map(async url => {
        const asset = await fetch(url, { cache: 'no-store' });
        if (asset.status !== 200) throw new Error('Incomplete media.');
        return asset;
      }));
      for (let index = 0; index < urls.length; index++) {
        await cache.put(urls[index], media[index]);
      }
      await cache.put(EPISODE_URL, response);
      return true;
    } catch { return false; }
  }

  function refreshEpisode() {
    if (!refreshPromise) {
      refreshPromise = cacheEpisode().finally(() => { refreshPromise = undefined; });
    }
    return refreshPromise;
  }

  async function cacheStatus() {
    const cache = await caches.open(CACHE_NAME);
    const episode = await cachedEpisode(cache);
    if (!episode) {
      // Incomplete first installs still allow streaming; quota is not a 404.
      if (!networkEpisode) await refreshEpisode();
      if (await cachedEpisode(cache)) return cacheStatus();
      let audioAvailable = false;
      try {
        if (networkEpisode) {
          audioAvailable = (await fetch(mediaURLs(networkEpisode)[0], { method: 'HEAD', cache: 'no-store' })).status === 200;
        }
      } catch { /* Offline without a committed episode. */ }
      return { audioAvailable, offlineReady: false, episode: networkEpisode };
    }
    const [audioURL, coverURL] = mediaURLs(episode);
    const audio = await cache.match(audioURL);
    const cover = await cache.match(coverURL);
    const shellReady = (await Promise.all(SHELL.map(url => cache.match(url)))).every(Boolean);
    return {
      audioAvailable: audio?.status === 200,
      offlineReady: audio?.status === 200 && cover?.status === 200 && shellReady,
      episode,
    };
  }

  self.addEventListener('install', event => {
    event.waitUntil((async () => {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(SHELL.map(url => new Request(url, { cache: 'reload' })));
      const complete = await refreshEpisode() && (await cacheStatus()).offlineReady;
      if (!complete) {
        const previous = (await caches.keys()).filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME);
        for (const key of previous) {
          if (await cachedEpisode(await caches.open(key))) {
            // Reject this update; the complete old worker and cache remain active.
            throw new Error('New episode is not fully cached.');
          }
        }
      }
      await self.skipWaiting();
    })());
  });

  self.addEventListener('activate', event => {
    event.waitUntil((async () => {
      if ((await cacheStatus()).offlineReady) {
        const keys = await caches.keys();
        await Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map(key => caches.delete(key)));
      }
      await self.clients.claim();
    })());
  });

  self.addEventListener('message', event => {
    if (!['GET_CACHE_STATUS', 'CACHE_EPISODE'].includes(event.data?.type)) return;
    event.waitUntil((async () => {
      try {
        if (event.data.type === 'CACHE_EPISODE') await refreshEpisode();
        event.ports[0]?.postMessage(await cacheStatus());
      } catch {
        event.ports[0]?.postMessage({ audioAvailable: false, offlineReady: false });
      }
    })());
  });

  self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const episode = await cachedEpisode(cache);
      const audioURL = episode ? mediaURLs(episode)[0] : null;
      const cached = await cache.match(request.url);
      if (cached) {
        if (request.url === audioURL) return buildRangeResponse(cached, request.headers.get('Range'));
        return cached;
      }
      try {
        const response = await fetch(request);
        // Only complete audio responses may enter the cache.
        if (request.url === audioURL && response.status === 200) {
          event.waitUntil(cache.put(audioURL, response.clone()).catch(() => {}));
        }
        return response;
      } catch {
        if (request.mode === 'navigate' && request.url.startsWith(BASE)) {
          const page = await cache.match(urlFor('./index.html'));
          if (page) return page;
        }
        return new Response('目前無法取得資源，請稍後再試。', {
          status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        });
      }
    })());
  });
}
