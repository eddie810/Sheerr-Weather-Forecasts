# Making Sheerr Weather graphics on your own computer

Everything from the cloud sessions (maps, charts, alert graphics, 3D videos) lives in this project. On your own
computer it runs the same way, but the 3D videos use your graphics card (minutes instead of an hour), and the
finished files land in a folder you can drag straight into Facebook or your TV software.

## 1. One-time setup (about 15–20 minutes, mostly waiting)

You only do this once.

1. **Get the project.** In the Claude desktop app, start a Code session on your computer (not in the cloud) and
   say: *"Clone eddie810/-sheerr-weather-voice, check out the claude/hello-xo6zr1 branch, and run the setup
   script."* Claude will ask before each install. Approve them.

   Or do it yourself in a terminal:

   ```
   git clone https://github.com/eddie810/-sheerr-weather-voice.git sheerr-graphics
   cd sheerr-graphics
   git checkout claude/hello-xo6zr1
   ```

2. **Run the setup script** from the project folder:
   - Mac: `bash tools/setup-mac.sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File tools\setup-windows.ps1`

   It installs Git, Node.js, Python, ffmpeg and Playwright's Chrome, downloads the map layers (~100 MB), and
   asks you to paste two keys:
   - `MAPBOX_ACCESS_TOKEN`: from your Mapbox account (maps and satellite)
   - `TWC_API_KEY`: The Weather Company key (town forecasts and alerts)

   At the end it renders a test graphic. If you see `render ok`, you're set.

3. **Restart the Claude app** so it picks up the keys.

## 2. Day to day

Open a Code session on your computer in the project folder and ask the way you do now:

- "Make tomorrow's highs maps for Newfoundland and Labrador, no sponsor"
- "Update the Island rain and snow maps with the 12Z RDPS"
- "A wind warning is out for the Burin, make the house-style map in 16:9 and 4:5"
- "Re-render the ECT 50 video with the latest data, 16:9"
- "Make a chart of today's peak gusts from these numbers: …"

Claude reads `CLAUDE.md` in this folder, so it already knows the scripts, data and house style. Finished
images and videos are saved next to each graphic's page (for example `graphics/nl-temps/nl-highs-today.png`).

**Driving it from your phone:** in a terminal in the project folder run `claude remote-control`. That session
then appears in the Claude app on your phone, and the work runs on your computer.

## 3. If something goes wrong

- **"MAPBOX_ACCESS_TOKEN" / "TWC_API_KEY" errors:** the keys didn't load. Restart the app, or run the setup
  script again and paste the key when asked.
- **3D video renders slowly:** it should use your graphics card automatically. Ask Claude to check `tools/gl.js`.
- **Euro wind or wave animation fails on `pygrib`:** that one package can be fussy to install. Ask Claude to
  install it (on a Mac, `brew install eccodes` first helps). Everything else works without it.
