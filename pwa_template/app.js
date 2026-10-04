'use strict';

const audio = document.getElementById('audio');
const playButton = document.getElementById('play');
const progress = document.getElementById('progress');
const backward = document.getElementById('backward');
const forward = document.getElementById('forward');
const message = document.getElementById('message');
const retry = document.getElementById('retry');
const offlineStatus = document.getElementById('offline-status');
let episode;
let registration;
let previewing = false;
let audioAvailable = false;

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

function actualDuration() {
  return Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0;
}

function updatePosition() {
  if (!('mediaSession' in navigator) || !navigator.mediaSession.setPositionState) return;
  try {
    const duration = actualDuration();
    if (duration) {
      navigator.mediaSession.setPositionState({
        duration,
        playbackRate: audio.playbackRate > 0 ? audio.playbackRate : 1,
        position: Math.min(duration, Math.max(0, audio.currentTime || 0)),
      });
    } else {
      navigator.mediaSession.setPositionState();
    }
  } catch { /* Older browsers may expose an unsupported position API. */ }
}

function updateProgress() {
  const duration = actualDuration() || episode?.durationSec || 0;
  const position = previewing ? Number(progress.value) : audio.currentTime || 0;
  progress.max = String(duration || 1);
  if (!previewing) progress.value = String(position);
  progress.style.setProperty('--progress', `${duration ? Math.min(100, position / duration * 100) : 0}%`);
  progress.setAttribute('aria-valuetext', `${formatTime(position)} / ${formatTime(duration)}`);
  document.getElementById('elapsed').textContent = formatTime(position);
  document.getElementById('duration').textContent = formatTime(duration);
  const canSeek = audioAvailable && actualDuration() > 0;
  progress.disabled = !canSeek;
  backward.disabled = !canSeek;
  forward.disabled = !canSeek;
  updatePosition();
}

function updatePlayback() {
  const playing = !audio.paused && !audio.ended;
  playButton.setAttribute('aria-label', playing ? '暫停' : '播放');
  document.getElementById('play-icon').hidden = playing;
  document.getElementById('pause-icon').hidden = !playing;
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
  updateProgress();
}

async function play() {
  if (!audioAvailable) return;
  try {
    // Keep play() in the original click/action stack for iOS user activation.
    await audio.play();
    message.textContent = '';
  } catch {
    message.textContent = '暫時無法播放，請再點一次播放，或重新檢查音訊。';
    retry.hidden = false;
  }
}

function seekTo(time, fast = false) {
  const duration = actualDuration();
  if (!audioAvailable || !duration || !Number.isFinite(time)) return;
  const target = Math.min(duration, Math.max(0, time));
  if (fast && typeof audio.fastSeek === 'function') audio.fastSeek(target);
  else audio.currentTime = target;
  updateProgress();
}

function setupMediaSession() {
  if (!('mediaSession' in navigator)) return;
  if ('MediaMetadata' in window) {
    const extension = new URL(episode.cover, location.href).pathname.split('.').pop().toLowerCase();
    const type = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', svg: 'image/svg+xml', webp: 'image/webp' }[extension];
    const artwork = [96, 128, 192, 256, 384, 512].map(size => ({
      src: new URL(episode.cover, location.href).href,
      sizes: `${size}x${size}`,
      ...(type ? { type } : {}),
    }));
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: episode.title, artist: episode.anchor, album: episode.show, artwork,
      });
    } catch { /* Metadata is optional on browsers with partial support. */ }
  }
  const handlers = {
    play,
    pause: () => audio.pause(),
    seekbackward: details => seekTo(audio.currentTime - (details.seekOffset ?? 15)),
    seekforward: details => seekTo(audio.currentTime + (details.seekOffset ?? 30)),
    seekto: details => seekTo(details.seekTime, details.fastSeek),
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { navigator.mediaSession.setActionHandler(action, handler); }
    catch { /* Safari versions support different subsets of actions. */ }
  }
}

function assetURL(value) {
  const url = new URL(value, location.href);
  if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol)) {
    throw new Error('Assets must be hosted on the same origin.');
  }
  return url.href;
}

function renderEpisode(data) {
  for (const key of ['show', 'title', 'anchor', 'published', 'audio', 'cover', 'description']) {
    if (typeof data[key] !== 'string' || !data[key].trim()) throw new Error('Invalid episode data.');
  }
  if (!Number.isFinite(data.durationSec) || data.durationSec < 0) throw new Error('Invalid duration.');
  episode = { ...data, audio: assetURL(data.audio), cover: assetURL(data.cover) };
  for (const key of ['show', 'anchor', 'published', 'description']) document.getElementById(key).textContent = episode[key];
  document.getElementById('episode-title').textContent = episode.title;
  document.title = `${episode.title} · ${episode.show}`;
  const cover = document.getElementById('cover');
  cover.src = episode.cover;
  cover.alt = `${episode.show}節目封面`;
  setupMediaSession();
  updateProgress();
}

function applyCacheStatus(status) {
  audioAvailable = status.audioAvailable === true;
  playButton.disabled = !audioAvailable;
  offlineStatus.textContent = status.offlineReady ? '已可離線收聽' : '';
  retry.hidden = audioAvailable;
  if (audioAvailable) {
    if (audio.src !== episode.audio || audio.error) {
      audio.src = episode.audio;
      audio.load();
    }
    message.textContent = audio.paused ? '音訊已就緒，點選播放開始收聽。' : '';
  } else {
    audio.pause();
    // Do not give the audio element a missing URL: no browser media error.
    audio.removeAttribute('src');
    audio.load();
    message.textContent = '本集音訊尚未上線，請稍後再試。';
  }
  updateProgress();
}

function askWorker(type) {
  return new Promise((resolve, reject) => {
    const worker = registration?.active;
    if (!worker) { reject(new Error('Service worker unavailable.')); return; }
    const channel = new MessageChannel();
    const timeout = setTimeout(() => {
      channel.port1.close();
      reject(new Error('Cache preparation timed out.'));
    }, 120000);
    channel.port1.onmessage = event => {
      clearTimeout(timeout);
      channel.port1.close();
      resolve(event.data);
    };
    worker.postMessage({ type }, [channel.port2]);
  });
}

async function checkAudio(refresh = false) {
  retry.disabled = true;
  message.textContent = '正在準備音訊與離線收聽…';
  try {
    if (registration?.active) {
      applyCacheStatus(await askWorker(refresh ? 'CACHE_EPISODE' : 'GET_CACHE_STATUS'));
    } else {
      // Playback still works in browsers without service worker support.
      const response = await fetch(episode.audio, { method: 'HEAD', cache: 'no-store' });
      applyCacheStatus({ audioAvailable: response.ok, offlineReady: false });
    }
  } catch {
    message.textContent = '目前無法取得音訊，請確認連線後重新檢查。';
    retry.hidden = false;
  } finally {
    retry.disabled = false;
  }
}

playButton.addEventListener('click', () => { if (audio.paused) void play(); else audio.pause(); });
backward.addEventListener('click', () => seekTo(audio.currentTime - 15));
forward.addEventListener('click', () => seekTo(audio.currentTime + 30));
progress.addEventListener('input', () => { previewing = true; updateProgress(); });
progress.addEventListener('change', () => {
  const target = Number(progress.value);
  previewing = false;
  seekTo(target);
});
progress.addEventListener('pointercancel', () => { previewing = false; updateProgress(); });
retry.addEventListener('click', () => { void checkAudio(true); });
for (const event of ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'ratechange']) audio.addEventListener(event, updateProgress);
for (const event of ['play', 'pause', 'ended']) audio.addEventListener(event, updatePlayback);
audio.addEventListener('waiting', () => { if (!audio.paused) message.textContent = '正在載入音訊…'; });
audio.addEventListener('playing', () => { message.textContent = ''; });
audio.addEventListener('error', () => {
  audioAvailable = false;
  playButton.disabled = true;
  message.textContent = '本集音訊暫時無法播放，請重新檢查音訊。';
  retry.hidden = false;
  updateProgress();
});

async function initialize() {
  // Start installation promptly; catch registration failures without blocking playback.
  const workerReady = 'serviceWorker' in navigator && window.isSecureContext
    ? prepareWorker()
    : Promise.resolve(null);
  try {
    const response = await fetch('./episode.json');
    if (!response.ok) throw new Error('Episode unavailable.');
    renderEpisode(await response.json());
    registration = await workerReady;
    await checkAudio();
  } catch {
    message.textContent = '暫時無法載入單集，請確認連線後重新開啟。';
    document.getElementById('episode-title').textContent = '新聞快報';
  }
}

async function prepareWorker() {
  let timeout;
  try {
    await navigator.serviceWorker.register('./sw.js');
    // ready does not reject when installation fails (e.g. storage quota).
    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise(resolve => { timeout = setTimeout(() => resolve(null), 30000); }),
    ]);
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

void initialize();
