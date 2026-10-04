import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../sw.js', import.meta.url), 'utf8');
const context = vm.createContext({ Response, Headers });
vm.runInContext(source, context);
const buildRangeResponse = context.buildRangeResponse;
const bytes = Uint8Array.from({ length: 200 }, (_, index) => index);
const fullResponse = () => new Response(bytes, {
  headers: { 'Content-Type': 'audio/mpeg', 'Content-Length': '999', 'Content-Encoding': 'gzip' },
});

for (const { name, range, start, end } of [
  { name: 'first two bytes', range: 'bytes=0-1', start: 0, end: 1 },
  { name: 'open-ended range', range: 'bytes=100-', start: 100, end: 199 },
  { name: 'suffix range', range: 'bytes=-50', start: 150, end: 199 },
  { name: 'end clamped to file size', range: 'bytes=190-999', start: 190, end: 199 },
  { name: 'suffix longer than file', range: 'bytes=-300', start: 0, end: 199 },
  { name: 'single last byte', range: 'bytes=199-199', start: 199, end: 199 },
]) {
  test(name, async () => {
    const input = fullResponse();
    const response = await buildRangeResponse(input, range);
    assert.equal(response.status, 206);
    assert.equal(response.headers.get('Content-Range'), `bytes ${start}-${end}/200`);
    assert.equal(response.headers.get('Content-Length'), String(end - start + 1));
    assert.equal(response.headers.get('Accept-Ranges'), 'bytes');
    assert.equal(response.headers.get('Content-Type'), 'audio/mpeg');
    assert.equal(response.headers.get('Content-Encoding'), null);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), bytes.slice(start, end + 1));
    assert.equal(input.bodyUsed, false, 'the caller can reuse its complete response');
  });
}

test('no Range returns the complete 200 body', async () => {
  const response = await buildRangeResponse(fullResponse(), null);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Length'), '200');
  assert.equal(response.headers.get('Content-Range'), null);
  assert.equal(response.headers.get('Accept-Ranges'), 'bytes');
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), bytes);
});

for (const range of ['bytes=200-', 'bytes=999-1000', 'bytes=100-50', 'bytes=-0', 'bytes=-', 'bytes=9007199254740992-']) {
  test(`${range} returns 416`, async () => {
    const response = await buildRangeResponse(fullResponse(), range);
    assert.equal(response.status, 416);
    assert.equal(response.headers.get('Content-Range'), 'bytes */200');
    assert.equal(response.headers.get('Content-Length'), '0');
    assert.equal(response.headers.get('Accept-Ranges'), 'bytes');
    assert.equal((await response.arrayBuffer()).byteLength, 0);
  });
}

test('an empty file has no satisfiable range', async () => {
  const response = await buildRangeResponse(new Response(new Uint8Array()), 'bytes=0-1');
  assert.equal(response.status, 416);
  assert.equal(response.headers.get('Content-Range'), 'bytes */0');
});

test('unsupported multipart or malformed syntax safely returns full 200', async () => {
  for (const range of ['bytes=0-1,100-101', 'items=0-1', 'bytes=abc-def']) {
    const response = await buildRangeResponse(fullResponse(), range);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Content-Range'), null);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), bytes);
  }
});
