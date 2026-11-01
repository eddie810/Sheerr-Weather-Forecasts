const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch(require('../../../tools/gl'));
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('console', m => console.log('console:', m.text())); p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://127.0.0.1:8765/scene.html?export' + (process.env.REGION ? '&region=' + process.env.REGION : ''));
  await p.waitForFunction(() => window.READY, null, { timeout: 60000 });
  for (const t of process.argv.slice(2)) { await p.evaluate(t => window.setT(+t), t); await (await p.$('#graphic')).screenshot({ path: path.join(__dirname, 't' + t + '.png') }); }
  await b.close();
})();
