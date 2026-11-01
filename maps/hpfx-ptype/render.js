// Render the radar precip-type loop (16:9) to MP4. No server needed.
//   [FPS=60] node render.js [out.mp4]
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path'), url = require('url');
(async () => {
  const STORY = false, fps = +(process.env.FPS || 60), dir = __dirname;
  const out = process.argv[2] || (STORY ? 'radar-ptype-loop.mp4' : 'radar-ptype-loop.mp4'), tmp = path.join(dir, STORY ? '_frames' : '_frames');
  fs.rmSync(tmp, { recursive: true, force: true }); fs.mkdirSync(tmp);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: STORY ? { width: 1112, height: 1970 } : { width: 1952, height: 1130 } });
  await p.goto(url.pathToFileURL(path.join(dir, 'index.html')).href + '?export');
  await p.waitForFunction(() => window.READY && document.fonts.status === 'loaded', null, { timeout: 60000 });
  await p.waitForTimeout(800);
  const n = Math.ceil(await p.evaluate(() => window.ANIM_LEN) * fps), g = await p.$('#graphic');
  for (let i = 0; i < n; i++) {
    await p.evaluate(t => window.setT(t), i / fps);
    await g.screenshot({ path: path.join(tmp, String(i).padStart(4, '0') + '.png') });
    if (i % 300 === 0) console.log(i, '/', n);
  }
  await b.close();
  execFileSync('ffmpeg', ['-y', '-framerate', String(fps), '-i', path.join(tmp, '%04d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    '-crf', '18', '-movflags', '+faststart', path.resolve(dir, out)], { stdio: 'ignore' });
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(n, 'frames ->', out);
})();
