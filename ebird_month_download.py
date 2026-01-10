
# ebird_month_download.py
# Example:
#   python ebird_month_download.py --username YOUR_USER --password YOUR_PASS \
#       --region SE --year 2024 --month 9 --out ./downloads_2024_09 --max 5

import time, re, argparse
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(
        description="Download eBird per-checklist files for a given year-month using direct download URLs (English UI)."
    )
    p.add_argument("--username", required=True, help="eBird/Cornell Lab username")
    p.add_argument("--password", required=True, help="eBird/Cornell Lab password")
    p.add_argument("--region", default="SE", help="Region code (e.g., 'SE', 'US-NY')")
    p.add_argument("--year", type=int, required=True, help="Year, e.g., 2024")
    p.add_argument("--month", type=int, required=True, choices=range(1, 13), help="Month 1-12")
    p.add_argument("--out", type=str, default=None, help="Output folder for downloads")
    p.add_argument("--headless", action="store_true", help="Run Chrome headless")
    p.add_argument("--max", type=int, default=None, help="Max checklists to process (for testing)")
    args = p.parse_args()
    args.month_str = f"{args.year}-{args.month:02d}"
    if not args.out:
        args.out = f"./ebird_downloads_{args.year}_{args.month:02d}"
    return args


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
def collect_subids(driver):
    """
    Scan the filtered page for checklist IDs:
    - From links like /checklist/S123456789
    - (Fallback) from any href containing 'subID=S...'
    Scroll until no new IDs appear (lazy-load).
    """
    subids = set()
    last_count = -1
    for _ in range(15):
        anchors = driver.find_elements(By.TAG_NAME, "a")
        for a in anchors:
            href = a.get_attribute("href") or ""
            m = re.search(r"/checklist/(S\d+)", href)
            if m:
                subids.add(m.group(1))
            m2 = re.search(r"subID=(S\d+)", href)
            if m2:
                subids.add(m2.group(1))
        if len(subids) == last_count:
            break
        last_count = len(subids)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)
    return sorted(subids)


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
    return True


# ---------- Main ----------
def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = build_driver(out_dir, headless=args.headless)
    try:
        login(driver, args.username, args.password)
        go_to_filtered_my_checklists(driver, args.region, args.year, args.month)

        subids = collect_subids(driver)
        if args.max:
            subids = subids[:args.max]
        print(f"Found {len(subids)} checklist IDs for {args.year}-{args.month:02d} (filtered view).")

        downloaded = 0
        for i, sid in enumerate(subids, 1):
            print(f"[{i}/{len(subids)}] {sid}")
            try:
                if download_by_subid(driver, sid, out_dir):
                    downloaded += 1
                time.sleep(0.7)  # polite pacing
            except Exception as e:
                print(f"  Failed: {e}")

        print(f"Done. Downloaded {downloaded} files to {out_dir.resolve()}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

