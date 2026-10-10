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
  const CACHE_VERSION = 'v1';
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

  async function cacheMedia(cache, url) {
    try {
      // No Range header: Cache API must receive a complete 200, never a 206.
      const response = await fetch(url, { cache: 'no-store' });
      if (response.status === 200) await cache.put(url, response);
      else if (response.status === 404) await cache.delete(url);
    } catch { /* A missing asset/network outage must not break shell installation. */ }
  }

  async function cacheEpisode() {
    const cache = await caches.open(CACHE_NAME);
    try {
      const response = await fetch(EPISODE_URL, { cache: 'no-store' });
      if (response.status === 200) {
        const episode = await response.clone().json();
        mediaURLs(episode);
        await cache.put(EPISODE_URL, response);
      }
    } catch { /* Keep an existing episode when refreshing offline. */ }
    const episode = await cachedEpisode(cache);
    if (episode) await Promise.all(mediaURLs(episode).map(url => cacheMedia(cache, url)));
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
    if (!episode) return { audioAvailable: false, offlineReady: false };
    const [audioURL, coverURL] = mediaURLs(episode);
    const audio = await cache.match(audioURL);
    const cover = await cache.match(coverURL);
    const shellReady = (await Promise.all(SHELL.map(url => cache.match(url)))).every(Boolean);
    return {
      audioAvailable: audio?.status === 200,
      offlineReady: audio?.status === 200 && cover?.status === 200 && shellReady,
    };
  }

  self.addEventListener('install', event => {
    event.waitUntil((async () => {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(SHELL);
      await refreshEpisode();
      await self.skipWaiting();
    })());
  });

  self.addEventListener('activate', event => {
    event.waitUntil((async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map(key => caches.delete(key)));
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
          event.waitUntil(cache.put(audioURL, response.clone()));
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
