// Screenshot single frames: node test.js 2 10 20 ... (seconds) -> t<sec>.png
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('file://' + path.join(__dirname, 'index.html') + '?export');
  await p.waitForFunction(() => window.READY, null, { timeout: 60000 });
  console.log('ANIM_LEN', await p.evaluate(() => window.ANIM_LEN));
  for (const t of process.argv.slice(2)) {
    await p.evaluate(t => window.setT(+t), t);
    await (await p.$('#graphic')).screenshot({ path: path.join(__dirname, 't' + t + '.png') });
  }
  await b.close();
})();
