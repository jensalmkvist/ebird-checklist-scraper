
# ebird_month_download.py
# Example:
#   python ebird_month_download.py --username YOUR_USER --password YOUR_PASS \
#       --region SE --year 2024 --month 9 --out ./downloads_2024_09 --max 5
#   python ebird_month_download.py --start 2026-10-15 --end 2026-11-01 --skip-ids imported.txt

import time, re, argparse, csv, html, os, getpass
from datetime import datetime, date, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ---------- CLI ----------
def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {s}")


def last_day_of_month(year: int, month: int) -> date:
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def parse_args():
    p = argparse.ArgumentParser(
        description="Download eBird per-checklist files for a year-month or a date range using direct download URLs (English UI)."
    )
    p.add_argument("--username", default=os.environ.get("EBIRD_USERNAME"),
                   help="eBird/Cornell Lab username (default: $EBIRD_USERNAME)")
    p.add_argument("--password", default=os.environ.get("EBIRD_PASSWORD"),
                   help="eBird/Cornell Lab password (default: $EBIRD_PASSWORD, else prompt)")
    p.add_argument("--region", default="SE", help="Region code (e.g., 'SE', 'US-NY')")
    p.add_argument("--year", type=int, help="Year, e.g., 2024 (with --month)")
    p.add_argument("--month", type=int, choices=range(1, 13), help="Month 1-12 (with --year)")
    p.add_argument("--start", type=parse_date, help="First date, YYYY-MM-DD (instead of --year/--month)")
    p.add_argument("--end", type=parse_date, help="Last date, YYYY-MM-DD (default: today)")
    p.add_argument("--skip-ids", type=str, default=None,
                   help="Text file with checklist IDs (one per line) not to download, e.g. already imported")
    p.add_argument("--out", type=str, default=None, help="Output folder for downloads")
    p.add_argument("--headless", action="store_true", help="Run Chrome headless")
    p.add_argument("--max", type=int, default=None, help="Max checklists to process (for testing)")
    p.add_argument("--no-coords", action="store_true",
                   help="Don't add Latitude/Longitude columns (skips visiting each checklist page)")
    args = p.parse_args()
    if not args.username:
        p.error("--username or $EBIRD_USERNAME is required")
    if not args.password:
        args.password = getpass.getpass("eBird password: ")
    if args.start:
        if args.year or args.month:
            p.error("use either --start/--end or --year/--month")
        args.end = args.end or date.today()
        if args.end < args.start:
            p.error("--end is before --start")
        if not args.out:
            args.out = f"./ebird_downloads_{args.start}_{args.end}"
    elif args.year and args.month:
        if args.end:
            p.error("--end needs --start")
        args.start = date(args.year, args.month, 1)
        args.end = last_day_of_month(args.year, args.month)
        if not args.out:
            args.out = f"./ebird_downloads_{args.year}_{args.month:02d}"
    else:
        p.error("give --start [--end], or --year and --month")
    return args


def months_between(start: date, end: date):
    """Yield (year, month) for every month from start to end, inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------- Browser setup ----------
def build_driver(download_dir: Path, headless: bool):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    # Ensure silent auto-downloads
    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=opts)  # Selenium 4 uses Selenium Manager
    return driver


# ---------- Auth and navigation ----------
def login(driver, username, password):
    driver.get("https://ebird.org/myebird")
    wait = WebDriverWait(driver, 40)
    user = wait.until(EC.presence_of_element_located((By.NAME, "username")))
    pwd  = wait.until(EC.presence_of_element_located((By.NAME, "password")))
    user.clear(); user.send_keys(username)
    pwd.clear();  pwd.send_keys(password)
    pwd.submit()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    time.sleep(2)


def build_filtered_url(region: str, year: int, month: int) -> str:
    # Direct filtered view (as you provided)
    return (
        f"https://ebird.org/mychecklists/{region}"
        f"?region=&location=&year={year}&m={month}&d=&sharedFilter=all&withMedia=&projId=&currentRow=1"
    )


def go_to_filtered_my_checklists(driver, region: str, year: int, month: int):
    url = build_filtered_url(region, year, month)
    driver.get(url)
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    time.sleep(1.0)


# ---------- Collect subIDs ----------
# Checklist links carry the date in their title:
#   title="Checklist S406014937 - Wednesday, October 28, 2026, 11:58 AM"
_TITLE_DATE = re.compile(r"Checklist (S\d+) - \w+, (\w+ \d{1,2}, \d{4})")


def collect_subids(driver):
    """
    Scan the filtered page for checklist IDs:
    - From links like /checklist/S123456789
    - (Fallback) from any href containing 'subID=S...'
    Scroll until no new IDs appear (lazy-load).
    Returns {subID: date or None}, the date read from the link title.
    """
    subids = {}
    last_count = -1
    for _ in range(15):
        anchors = driver.find_elements(By.TAG_NAME, "a")
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = re.search(r"/checklist/(S\d+)", href) or re.search(r"subID=(S\d+)", href)
            if not m:
                continue
            sid = m.group(1)
            subids.setdefault(sid, None)
            mt = _TITLE_DATE.search(a.get_attribute("title") or "")
            if mt and mt.group(1) == sid:
                try:
                    subids[sid] = datetime.strptime(mt.group(2), "%B %d, %Y").date()
                except ValueError:
                    pass
        if len(subids) == last_count:
            break
        last_count = len(subids)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)
    return subids


# ---------- Location coordinates ----------
# eBird's checklist CSV has no coordinates, but the checklist page links the
# location to a map. These patterns cover the usual ways a page embeds them.
_NUM_LAT = r"(-?\d{1,2}\.\d+)"
_NUM_LON = r"(-?\d{1,3}\.\d+)"
_SEP = r"\s*(?:,|%2C)\s*"
_GMAPS = r"(?:google\.[a-z.]+/maps|maps\.google\.[a-z.]+/)"
COORD_PATTERNS = [
    # Google Maps links: ...maps/search/?api=1&query=LAT,LON  /  ?q=LAT,LON  /  ?ll=LAT,LON
    re.compile(_GMAPS + r"[^\"'\s<>]*?[?&](?:query|q|ll|daddr|destination)=" + _NUM_LAT + _SEP + _NUM_LON, re.I),
    # Google Maps "@LAT,LON" style
    re.compile(_GMAPS + r"[^\"'\s<>]*?@" + _NUM_LAT + _SEP + _NUM_LON, re.I),
    # data-lat / data-lng attributes
    re.compile(r"data-lat(?:itude)?=[\"']" + _NUM_LAT + r"[\"'][^>]*?data-(?:lng|lon|long|longitude)=[\"']" + _NUM_LON, re.I),
    # JSON: "lat": 58.3, "lng": 13.5  /  "latitude":58.3,"longitude":13.5
    re.compile(r"[\"']lat(?:itude)?[\"']\s*:\s*[\"']?" + _NUM_LAT + r"[\"']?\s*,\s*[\"'](?:lng|lon|long|longitude)[\"']\s*:\s*[\"']?" + _NUM_LON, re.I),
]


def find_coords(page_html: str):
    """Return (lat, lon) as strings from checklist page HTML, or None."""
    text = html.unescape(page_html or "")
    for pat in COORD_PATTERNS:
        for m in pat.finditer(text):
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0):
                return m.group(1), m.group(2)
    return None


def fetch_location_coords(driver, subid: str, debug_dir: Path = None):
    """Open the checklist page and read the location's coordinates.
    If none are found, the page HTML is saved to debug_dir for inspection."""
    # eBird sometimes redirects to a "session information has been lost" page
    # instead of the checklist; try again when we didn't land on the checklist.
    for attempt in range(3):
        driver.get(f"https://ebird.org/checklist/{subid}")
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        if f"/checklist/{subid}" in driver.current_url:
            break
        time.sleep(2 + 2 * attempt)
    # The map link is filled in after the page body loads, so poll for it.
    coords = None
    deadline = time.time() + 10
    while not coords and time.time() < deadline:
        time.sleep(0.5)
        coords = find_coords(driver.page_source)
    if not coords and debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{subid}.html").write_text(driver.page_source, encoding="utf-8")
    return coords


def add_coords_to_csv(csv_path: Path, coords):
    """Append Latitude/Longitude columns to a downloaded checklist CSV."""
    raw = csv_path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(text.splitlines()))
    if not rows or "Latitude" in rows[0]:
        return False
    lat, lon = coords
    rows[0] += ["Latitude", "Longitude"]
    for row in rows[1:]:
        if row:
            row += [lat, lon]
    with open(csv_path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)
    return True


# ---------- Direct download ----------
def download_by_subid(driver, subid: str, download_dir: Path):
    """
    Use the direct download endpoint for a checklist:
    https://ebird.org/checklist/download?subID=<S-ID>
    Then wait for a new file (csv/xls/xlsx) to appear in download_dir.
    """
    wait = WebDriverWait(driver, 30)
    before = {f.name for f in download_dir.glob("*")}
    url = f"https://ebird.org/checklist/download?subID={subid}"
    driver.get(url)  # triggers browser download
    # If a server-side error or login redirect occurs, the page won't download; check for body
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))

    deadline = time.time() + 120
    saved_name = None
    while time.time() < deadline:
        names = {f.name for f in download_dir.glob("*")}
        new_names = list(names - before)
        # Consider final and partial files
        finals = [n for n in new_names if n.lower().endswith((".csv", ".xls", ".xlsx"))]
        partials = [n for n in new_names if n.lower().endswith(".crdownload")]
        if finals:
            saved_name = finals[0]
            break
        if partials:
            # still downloading; keep waiting
            pass
        time.sleep(1.0)

    if not saved_name:
        raise RuntimeError(f"Download timeout for {subid}")

    # Prefix S-ID if missing
    if subid not in saved_name:
        src = download_dir / saved_name
        dst = download_dir / f"{subid}_{saved_name}"
        try:
            src.rename(dst)
            saved_name = dst.name
        except Exception:
            pass

    print(f"  Saved: {saved_name}")
    return download_dir / saved_name


# ---------- Main ----------
def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    skip = set()
    if args.skip_ids:
        skip_path = Path(args.skip_ids)
        if skip_path.exists():
            skip = {l.strip() for l in skip_path.read_text(encoding="utf-8").splitlines() if l.strip()}

    driver = build_driver(out_dir, headless=args.headless)
    try:
        login(driver, args.username, args.password)

        subids, skipped = [], 0
        for year, month in months_between(args.start, args.end):
            go_to_filtered_my_checklists(driver, args.region, year, month)
            found = collect_subids(driver)
            in_range = [sid for sid, d in sorted(found.items())
                        if d is None or args.start <= d <= args.end]
            new = [sid for sid in in_range if sid not in skip]
            skipped += len(in_range) - len(new)
            subids += new
            print(f"{year}-{month:02d}: {len(found)} checklists, {len(in_range)} in date range, {len(new)} new")
        if args.max:
            subids = subids[:args.max]
        print(f"Found {len(subids)} checklists to download for {args.start} to {args.end}"
              + (f" ({skipped} already imported, skipped)." if skipped else "."))

        downloaded, failed = 0, 0
        for i, sid in enumerate(subids, 1):
            print(f"[{i}/{len(subids)}] {sid}")
            try:
                coords = None
                if not args.no_coords:
                    try:
                        coords = fetch_location_coords(driver, sid, out_dir / "debug_pages")
                    except Exception as e:
                        print(f"  Could not read coordinates: {e}")
                saved = download_by_subid(driver, sid, out_dir)
                if saved:
                    downloaded += 1
                    if coords and saved.suffix.lower() == ".csv":
                        add_coords_to_csv(saved, coords)
                        print(f"  Location: {coords[0]}, {coords[1]}")
                    elif not args.no_coords:
                        print("  No coordinates found on checklist page")
                time.sleep(0.7)  # polite pacing
            except Exception as e:
                failed += 1
                print(f"  Failed: {e}")

        print(f"Done. Downloaded {downloaded} files to {out_dir.resolve()}"
              + (f"; {failed} failed." if failed else "."))
    finally:
        driver.quit()
    return failed


if __name__ == "__main__":
    # Exit code 1 when any checklist failed, so callers know the set is incomplete
    raise SystemExit(1 if main() else 0)

