#!/usr/bin/env bash
# Put an existing radar video into the Sheerr 1080x1350 frame without altering the video.
#   ./embed.sh input.mp4 output.mp4 ["Eyebrow"] ["Title"] ["Subtitle"]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
in="$1"; out="$2"
q="eyebrow=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "${3:-}")&title=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "${4:-}")&sub=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "${5:-}")"
NODE_PATH="$(npm root -g)" node -e '
const { chromium } = require("playwright");
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1080, height: 1350 } });
  await p.goto(process.argv[1]); await p.waitForTimeout(1500);
  const slot = await p.$eval("#slot", e => { const r = e.getBoundingClientRect(); return [r.top, r.height]; });
  await (await p.$("#graphic")).screenshot({ path: process.argv[2] });
  console.log(Math.round(slot[0]), Math.round(slot[1])); await b.close();
})();' "file://$here/frame.html?$q" "$here/_frame.png" > "$here/_slot.txt"
read top height < "$here/_slot.txt"
# scale the video to fill the slot width, centre it vertically in the slot, hold the last frame 1.5 s
ffmpeg -v error -y -loop 1 -i "$here/_frame.png" -i "$in" -filter_complex \
  "[1:v]scale=1080:-2,tpad=stop_mode=clone:stop_duration=1.5[v];[0:v][v]overlay=0:${top}+(${height}-overlay_h)/2:shortest=1,format=yuv420p" \
  -r 8 -c:v libx264 -crf 18 -movflags +faststart "$out"
rm -f "$here/_frame.png" "$here/_slot.txt"
echo "wrote $out"
