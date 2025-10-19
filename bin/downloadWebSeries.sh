#!/usr/bin/env bash
# =============================================================
#  downloadSeries.sh — Single-file Bash + Python webseries downloader
#  Usage:
#    ./downloadSeries.sh -u <url> [-t <threads>] [--dry-run]
# =============================================================

# Default values
URL=""
THREADS=4
DRY_RUN=false

source .venv/bin/activate

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--url) URL="$2"; shift 2;;
        -t|--threads) THREADS="$2"; shift 2;;
        --dry-run) DRY_RUN=true; shift;;
        *) echo "Usage: $0 -u <url> [-t <threads>] [--dry-run]"; exit 1;;
    esac
done

if [[ -z "$URL" ]]; then
    echo "Error: URL is required"
    exit 1
fi

# Check dependencies
for pkg in python3 aria2c; do
    command -v "$pkg" >/dev/null 2>&1 || { echo "❌ Missing dependency: $pkg"; exit 1; }
done

# Run the embedded Python script
python3 - "$URL" "$THREADS" "$DRY_RUN" <<'PYCODE'
import sys, os, subprocess, requests
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def list_links(url):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        pre = soup.find("pre")
        if not pre:
            return []
        return [a.get("href") for a in pre.find_all("a") if a.get("href") != "../"]
    except Exception as e:
        log(f"⚠️ Error fetching {url}: {e}")
        return []

def download_file(url, output, dry_run=False):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    if os.path.exists(output):
        log(f"✅ Skipped (exists): {output}")
        return
    if dry_run:
        log(f"📄 [Dry Run] Would download: {url} -> {output}")
        return
    log(f"⬇️ Downloading: {url}")
    subprocess.run([
        "aria2c", "-x16", "-s16", "-k1M",
        "-d", os.path.dirname(output),
        "-o", os.path.basename(output),
        url,
        "--continue=true"
    ], check=True)
    log(f"✅ Done: {output}")

def download_episodes(url, out_dir, dry_run=False, threads=4):
    links = list_links(url)
    eps = [l for l in links if any(l.lower().endswith(ext) for ext in ["mp4","mkv","avi","webm"])]
    if not eps:
        log(f"⚠️ No episodes found in {url}")
        return
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = [ex.submit(download_file, f"{url.rstrip('/')}/{ep}", os.path.join(out_dir, ep), dry_run) for ep in eps]
        for f in as_completed(futures):
            f.result()

def download_series(base_url, dry_run=False, threads=4):
    log(f"🌐 Fetching index: {base_url}")
    links = list_links(base_url)
    seasons = [l for l in links if l.lower().startswith("s") and l.endswith("/")]
    if not seasons:
        log("⚠️ No season folders found, downloading episodes directly.")
        download_episodes(base_url, ".", dry_run, threads)
        return
    for s in seasons:
        s_url = f"{base_url.rstrip('/')}/{s}"
        out_dir = s.rstrip("/")
        os.makedirs(out_dir, exist_ok=True)
        log(f"📂 Scanning season: {s_url}")
        download_episodes(s_url, out_dir, dry_run, threads)

def main():
    url = sys.argv[1]
    threads = int(sys.argv[2])
    dry_run = sys.argv[3].lower() == "true"
    log(f"Starting download from {url} with {threads} threads")
    if dry_run:
        log("🔍 Dry run mode enabled — no files will be downloaded")
    download_series(url, dry_run=dry_run, threads=threads)
    log("🎬 All done!")

if __name__ == "__main__":
    main()
PYCODE
