// Screenshot the 2D map area (no town cards/pins) at 2x as the 3D terrain texture.
//   NODE_PATH=$(npm root -g) node 3d/texture.js [region]
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const region = process.argv[2] || '', sfx = region ? '-' + region : '';
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 }, deviceScaleFactor: 2 });
  await p.goto('file://' + path.join(__dirname, '..', 'index.html') + '?export' + (region ? '&region=' + region : ''));
  await p.waitForTimeout(2500);
  await p.addStyleTag({ content: '#cards{display:none} .map svg line, .map svg circle{display:none} .map{border:0!important}' });
  await (await p.$('.map')).screenshot({ path: path.join(__dirname, 'texture' + sfx + '.png') });
  await b.close();
})();
