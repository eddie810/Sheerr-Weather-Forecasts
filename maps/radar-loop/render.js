// Screenshot every frame of loop.html, then build the GIF (feed, 720px) and MP4 (1080x1350).
//   NODE_PATH=$(npm root -g) node render.js
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

(async () => {
  const dir = __dirname, tmp = path.join(dir, '_shots');
  fs.rmSync(tmp, { recursive: true, force: true });
  fs.mkdirSync(tmp);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1350 } });
  await page.goto('file://' + path.join(dir, 'loop.html') + '?export&frame=0');
  await page.waitForTimeout(2000);                       // fonts + basemap
  const n = await page.evaluate(() => window.FRAME_COUNT);
  const g = await page.$('#graphic');
  let k = 0;
  for (let i = 0; i < n; i++) {
    await page.evaluate(i => window.show(i), i);
    const hold = i === n - 1 ? 8 : 1;                    // linger on the latest frame
    for (let h = 0; h < hold; h++) await g.screenshot({ path: path.join(tmp, String(k++).padStart(3, '0') + '.png') });
  }
  await browser.close();

  const inp = ['-y', '-framerate', '6', '-i', path.join(tmp, '%03d.png')];
  execFileSync('ffmpeg', [...inp, '-vf', 'scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=none',
    '-loop', '0', path.join(dir, 'radar-loop.gif')], { stdio: 'ignore' });
  execFileSync('ffmpeg', [...inp, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart',
    path.join(dir, 'radar-loop.mp4')], { stdio: 'ignore' });
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(n, 'frames ->', 'radar-loop.gif', 'radar-loop.mp4');
})();
