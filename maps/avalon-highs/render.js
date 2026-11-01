// Render the Avalon highs fly-over (index.html) to MP4 (1080x1350, 30 fps by default).
// RESUME=1 keeps frames already in the frame folder and renders only the missing ones.
// WORKERS=n renders with n browsers in parallel (default: half the CPU cores, up to 6, on your own computer; 1 in the cloud).
// Needs an HTTP server (ES module + fetch): python3 -m http.server 8768  (in avalon-highs)
//   [FPS=30] [WORKERS=4] node render.js [out.mp4]
const { chromium } = require('playwright');
const { execFileSync, spawn } = require('child_process');
const fs = require('fs'), path = require('path'), os = require('os');
const dir = __dirname, fps = +(process.env.FPS || 30), out = process.argv[2] || 'avalon-highs-3d.mp4',
  tmp = path.join(dir, '_3d'), SHARD = process.env.SHARD;                            // SHARD="k/n": this worker's slice
const WORKERS = SHARD ? 1 : +(process.env.WORKERS ||
  (process.env.CLAUDE_CODE_REMOTE === 'true' ? 1 : Math.max(1, Math.min(6, Math.floor(os.cpus().length / 2)))));

async function frames(k, n) {                      // render every n-th frame starting at k
  const b = await chromium.launch(require('../../tools/gl'));
  const p = await b.newPage({ viewport: { width: 1112, height: 1400 } });
  p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://127.0.0.1:8768/index.html?export');
  await p.waitForFunction(() => window.READY, null, { timeout: 90000 });
  const N = Math.ceil(await p.evaluate(() => window.ANIM_LEN) * fps);
  const g = await p.$('#graphic'), t0 = Date.now();
  for (let i = k; i < N; i += n) {
    const f = path.join(tmp, String(i).padStart(4, '0') + '.png');
    if (process.env.RESUME && fs.existsSync(f)) continue;
    await p.evaluate(t => window.setT(t), i / fps);
    await g.screenshot({ path: f });
    if (k === 0 && i % (100 * n) === 0 && i) console.log(`${i}/${N} frames, ${((i / n) / ((Date.now() - t0) / 1000) * n).toFixed(1)} fps overall`);
  }
  await b.close();
  return N;
}

(async () => {
  if (SHARD) { const [k, n] = SHARD.split('/').map(Number); await frames(k, n); return; }
  if (!process.env.RESUME) fs.rmSync(tmp, { recursive: true, force: true });
  fs.mkdirSync(tmp, { recursive: true });
  let n;
  if (WORKERS === 1) n = await frames(0, 1);
  else {
    console.log(`rendering with ${WORKERS} workers`);
    await Promise.all(Array.from({ length: WORKERS }, (_, k) => new Promise((res, rej) => {
      const c = spawn(process.execPath, [__filename], { env: { ...process.env, SHARD: `${k}/${WORKERS}`, RESUME: '1' }, stdio: 'inherit' });
      c.on('exit', code => code ? rej(new Error(`worker ${k} exited ${code}`)) : res());
    })));
    n = fs.readdirSync(tmp).filter(f => f.endsWith('.png')).length;
  }
  execFileSync('ffmpeg', ['-y', '-framerate', String(fps), '-i', path.join(tmp, '%04d.png'), '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', path.resolve(dir, out)], { stdio: 'ignore' });
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(n, 'frames ->', out);
})();
