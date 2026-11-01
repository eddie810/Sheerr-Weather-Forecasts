// Screenshot the #graphic element of a page to PNG (used for every static graphic).
//   node tools/shot.js "<file path>/index.html?export&fmt=tv" out.png [viewport width] [viewport height]
// Viewport defaults fit 4:5 social (1080x1350); pass 1952 1130 for 16:9 or 1300 760 for a 1280x720 thumbnail.
const { chromium } = require('playwright');
(async () => {
  const [url, out, vw = 1112, vh = 1400] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +vw, height: +vh }, deviceScaleFactor: 1 });
  const [file, query] = url.split('?');                           // file path -> file:// URL (works on Windows too)
  await p.goto(url.startsWith('http') ? url : require('url').pathToFileURL(require('path').resolve(file)).href + (query ? '?' + query : ''));
  await p.waitForTimeout(2500);                                    // web fonts + images
  await (await p.$('#graphic')).screenshot({ path: out });
  await b.close();
})();
