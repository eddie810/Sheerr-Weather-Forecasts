// Render the 3D wave scene (index.html) to MP4 (1080x1350, 30 fps).
// Needs an HTTP server (ES module + fetch): python3 -m http.server 8766  (in waves-3d)
//   NODE_PATH=$(npm root -g) node render.js [out.mp4]
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
(async () => {
  const dir = __dirname, out = process.argv[2] || 'waves-3d.mp4', tmp = path.join(dir, '_3d');
  fs.rmSync(tmp, { recursive: true, force: true }); fs.mkdirSync(tmp);
  const b = await chromium.launch(require('../../tools/gl'));
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://127.0.0.1:8766/index.html?export');
  await p.waitForFunction(() => window.READY, null, { timeout: 90000 });
  const len = await p.evaluate(() => window.ANIM_LEN), fps = 30, n = Math.ceil(len * fps);
  const g = await p.$('#graphic');
  for (let i = 0; i < n; i++) {
    await p.evaluate(t => window.setT(t), i / fps);
    await g.screenshot({ path: path.join(tmp, String(i).padStart(4, '0') + '.png') });
  }
  await b.close();
  execFileSync('ffmpeg', ['-y', '-framerate', String(fps), '-i', path.join(tmp, '%04d.png'), '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', path.join(dir, out)], { stdio: 'ignore' });
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(n, 'frames ->', out);
})();
