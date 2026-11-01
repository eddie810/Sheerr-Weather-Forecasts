// Render the 3D terrain scene (scene.html) to MP4 (1080x1350, 30 fps).
// Needs an HTTP server (ES modules): python3 -m http.server 8765  (in nl-temps)
//   NODE_PATH=$(npm root -g) node 3d/render.js [region] [out.mp4]
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
(async () => {
  const region = process.argv[2] || '', dir = path.join(__dirname, '..'),
    out = process.argv[3] || (region ? region + '-highs-3d.mp4' : 'nl-highs-3d.mp4'), tmp = path.join(dir, '_3d');
  fs.rmSync(tmp, { recursive: true, force: true }); fs.mkdirSync(tmp);
  const b = await chromium.launch(require('../../../tools/gl'));
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://127.0.0.1:8765/scene.html?export' + (region ? '&region=' + region : ''));
  await p.waitForFunction(() => window.READY, null, { timeout: 60000 });
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
