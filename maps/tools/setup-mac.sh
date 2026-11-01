#!/bin/bash
# One-time setup of the Sheerr Weather graphics on a Mac. Run from the project folder:
#   bash tools/setup-mac.sh
# Safe to run again: it skips what is already installed.
set -e
cd "$(dirname "$0")/.."
echo "== Sheerr Weather graphics setup (Mac) =="

# 1. Homebrew (the Mac package manager), then the tools
if ! command -v brew >/dev/null; then
  echo "Installing Homebrew (it will ask for your Mac password)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi
brew install git node@22 python ffmpeg
# Node 22 LTS: Playwright's browser download can freeze at 100% on newer Node releases
export PATH="$(brew --prefix node@22)/bin:$PATH"
grep -q 'node@22/bin' ~/.zshrc 2>/dev/null || echo 'export PATH="$(brew --prefix node@22)/bin:$PATH"' >> ~/.zshrc
rm -rf ~/Library/Caches/ms-playwright/__dirlock      # left behind if an earlier download was interrupted
brew install eccodes || true                      # for pygrib (optional)

# 2. Python packages in a project-local environment (.venv)
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pygrib || echo "  (pygrib skipped: only the Euro wind / wave animations need it)"

# 3. Playwright + its Chrome, used to turn pages into PNG/MP4
npm install
npx playwright install chromium

# 4. Map layers (~100 MB, not in git)
.venv/bin/python tools/get_data.py

# 5. API keys, saved in ~/.zshrc so every terminal and Claude session sees them
for KEY in MAPBOX_ACCESS_TOKEN TWC_API_KEY; do
  if ! grep -q "export $KEY=" ~/.zshrc 2>/dev/null; then
    read -r -p "Paste your $KEY (Enter to skip): " VAL
    [ -n "$VAL" ] && echo "export $KEY=\"$VAL\"" >> ~/.zshrc
  fi
done

# 6. Quick check: render a static graphic
.venv/bin/python -c "import numpy, scipy, matplotlib, PIL, shapefile; print('python ok')"
node tools/shot.js "graphics/storm-types/index.html?export&fmt=social" /tmp/sheerr-test.png && echo "render ok: /tmp/sheerr-test.png"
echo "== Done. Open a new terminal (or restart the Claude app) so the keys load. =="
