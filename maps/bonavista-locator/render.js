// Overlay the Bonavista locator card and the video credit on a viewer clip (9:16, output 1080x1920).
// Renders the page's transparent overlay frame by frame, then composites it on the clip with ffmpeg (audio kept).
//   node render.js "<input video>" [out.mp4]
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path'), url = require('url');

const [src, out = path.join(__dirname, 'bonavista-video.mp4')] = process.argv.slice(2);
const FPS = 30, STILL = 7.0;          // the overlay stops changing after STILL s; later frames reuse the last one
(async () => {
  const dur = +execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src]).toString();
  const dir = path.join(__dirname, 'frames');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  await p.goto(url.pathToFileURL(path.join(__dirname, 'index.html')).href + '?export');
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(500);
  const n = Math.ceil(dur * FPS), live = Math.min(n, Math.ceil(STILL * FPS));
  for (let i = 0; i < live; i++) {
    await p.evaluate(t => window.setT(t), i / FPS);
    await p.screenshot({ path: path.join(dir, `${String(i).padStart(4, '0')}.png`), omitBackground: true });
  }
  await b.close();
  for (let i = live; i < n; i++)
    fs.copyFileSync(path.join(dir, `${String(live - 1).padStart(4, '0')}.png`), path.join(dir, `${String(i).padStart(4, '0')}.png`));
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', src, '-framerate', String(FPS), '-i', path.join(dir, '%04d.png'),
    '-filter_complex', '[0:v]fps=30,scale=1080:1920:flags=lanczos,setsar=1[v];[v][1:v]overlay=0:0:shortest=1[o]',
    '-map', '[o]', '-map', '0:a?', '-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p',
    '-c:a', 'copy', '-movflags', '+faststart', out], { stdio: 'inherit' });
  console.log('wrote', out, n, 'frames');
})();
