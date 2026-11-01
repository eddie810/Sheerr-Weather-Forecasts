// Chromium launch options for the WebGL (three.js) renders.
// On a cloud session (no graphics card) WebGL runs in software (SwiftShader): slow but works everywhere.
// On your own computer it runs the full Chromium in "new headless" mode so WebGL uses the graphics card
// (Metal on a Mac). Force either with GL=software or GL=gpu.
const cloud = process.env.CLAUDE_CODE_REMOTE === 'true';
const mode = process.env.GL || (cloud ? 'software' : 'gpu');
module.exports = mode === 'software'
  ? { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] }
  : { channel: 'chromium', args: ['--ignore-gpu-blocklist', '--enable-gpu', '--enable-gpu-rasterization',
      ...(process.platform === 'darwin' ? ['--use-angle=metal'] : [])] };
