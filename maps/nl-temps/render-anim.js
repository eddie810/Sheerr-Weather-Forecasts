// Render the ?anim mode of index.html to MP4 (1080x1350, 30 fps).
//   NODE_PATH=$(npm root -g) node render-anim.js [region] [out.mp4]
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path');
(async () => {
  const region = process.argv[2] || '', out = process.argv[3] || 'highs-anim.mp4';
  const dir = __dirname, tmp = path.join(dir, '_anim');
  fs.rmSync(tmp, { recursive: true, force: true }); fs.mkdirSync(tmp);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  await p.goto('file://' + path.join(dir, 'index.html') + '?export&anim' + (region ? '&region=' + region : ''));
  await p.waitForTimeout(2500);
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
