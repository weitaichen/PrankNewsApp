// Node 24 treats an explicit directory argument as a module entry point.
// Keep the requested `node --test pwa_template/tests/` command portable.
(async () => {
  await import('./range.test.mjs');
  await import('./sw.test.mjs');
  await import('./app.test.mjs');
})().catch(error => {
  process.exitCode = 1;
  throw error;
});
