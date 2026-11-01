// Screenshot single frames of the fly-over: node test.js 2 6 12 ... (seconds) -> t<sec>.png
// Needs the HTTP server: python3 -m http.server 8768  (in avalon-highs)
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch(require('../../tools/gl'));
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://127.0.0.1:8768/index.html?export');
  await p.waitForFunction(() => window.READY, null, { timeout: 90000 });
  console.log('ANIM_LEN', await p.evaluate(() => window.ANIM_LEN));
  for (const t of process.argv.slice(2)) {
    await p.evaluate(t => window.setT(+t), t);
    await (await p.$('#graphic')).screenshot({ path: path.join(__dirname, 't' + t + '.png') });
  }
  await b.close();
})();
