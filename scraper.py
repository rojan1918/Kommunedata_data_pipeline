import os
import re
import time
import csv
import pandas as pd
import datetime
from glob import glob
from urllib.parse import urlparse

# Import shared utils
import scraper_utils

# Import Selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
except ImportError:
    print("Error: Selenium library not found. Run: pip install selenium")
    exit()

# Import BeautifulSoup
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: BeautifulSoup library not found. Run: pip install beautifulsoup4")
    exit()

# --- CONFIGURATION ---

COMMITTEE_CONFIGS = {
    'Oekonomi': 'found_start_urls.csv',
    'Teknik': 'found_start_urls_teknikmiljoe.csv',
    'Byraad': 'found_start_urls_byraad.csv',
    'Plan': 'found_start_urls_plan.csv'
}

# Pull limit from env via shared helper (None means unlimited)
MAX_DOWNLOADS = scraper_utils.get_download_limit()
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
IS_RENDER = os.environ.get('RENDER') == 'true'

def get_driver(download_dir):
    """
    Initializes a new driver for each municipality to ensure
    downloads go to the correct specific folder.
    """
    chrome_options = Options()
    
    # Render Specific
    if IS_RENDER:
        chrome_options.add_argument("--headless=new")
        chrome_options.binary_location = "/usr/bin/chromium"
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")
    else:
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")

    # Configure download folder dynamically
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if IS_RENDER:
         print(f"   Binary: /usr/bin/chromium")
         # Selenium Manager finds driver automatically on Render if installed via apt
         driver = webdriver.Chrome(options=chrome_options)
    else:
        driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
        if not os.path.exists(driver_path):
            driver_path = 'chromedriver'  # Fallback
        
        service = Service(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
    return driver


def get_meeting_links(driver, start_url, base_url):
    """
    Scrapes meeting links using infinite scroll.
    Respects the global MAX_DOWNLOADS limit to stop scrolling early if possible.
    """
    print(f"   > Finding Meeting Pages on {start_url}...")
    driver.get(start_url)
    
    # ... (rest of the logic remains same until we implement better filtering logic here if possible)
    # Actually, we can't filter by date effectively here without visiting the link or parsing text if available.
    # The current logic collects all links then processes them.
    # We will filter in process_download to save bandwidth/time on PDF downloads, 
    # but we still have to find the links.
    
    try:
        # Wait for the first link to ensure page loaded
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/vis?Referat-']"))
        )
    except TimeoutException:
        print("   > Warning: Page loaded but no meeting links found (or timed out).")
        return []

    seen_links = set()
    ordered_links = []
    last_total_count = 0

    while True:
        # Parse current page state
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        links = soup.find_all('a', href=lambda h: h and h.startswith('/vis?Referat-'))

        for link in links:
            href = link.get('href')
            # Ensure we construct the full URL using the correct Base URL
            full_url = base_url.rstrip('/') + href if href.startswith('/') else base_url + '/' + href

            if full_url not in seen_links:
                seen_links.add(full_url)
                ordered_links.append(full_url)

                # Optimization: If we have a limit, stop collecting once we reach it
                if MAX_DOWNLOADS and len(ordered_links) >= MAX_DOWNLOADS:
                    print(f"   > Reached limit of {MAX_DOWNLOADS} meetings.")
                    return ordered_links

        print(f"   > Found {len(ordered_links)} unique links so far...")

        if len(ordered_links) == last_total_count:
            print("   > No new links loaded. Finished scrolling.")
            break

        last_total_count = len(ordered_links)

        # Scroll down
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.5)

    return ordered_links


def process_download(driver, meeting_url, base_url, download_dir, muni_name, committee_source):
    """
    Downloads a single PDF.
    Uses the dynamic base_url to construct the download link.
    """
    try:
        # Extract UUID
        uuid_match = re.search(r"id=([a-f0-9\-]{36})", meeting_url)
        if not uuid_match:
            print(f"     Skipping (No UUID found): {meeting_url}")
            return
        uuid = uuid_match.group(1)

        # Determine Date for filename
        date_match = re.search(r'd\.(\d{2}-\d{2}-\d{4})', meeting_url)
        date_obj = None
        if date_match:
            d_str, m_str, y_str = date_match.group(1).split('-')
            filename = f"{y_str}-{m_str}-{d_str}_{muni_name}_oekonomiudvalget.pdf"
            try:
                date_obj = datetime.date(int(y_str), int(m_str), int(d_str))
            except:
                pass
        else:
            filename = f"{muni_name}_oekonomiudvalget_{uuid}.pdf"

        # --- DATE FILTERING ---
        if date_obj and not scraper_utils.should_scrape(date_obj):
             # print(f"     Skipping (Old/Filtered Date): {filename}")
             return

        # Determine Paths
        local_path = os.path.join(download_dir, filename)
        
        # Modify bucket name based on committee source
        bucket_suffix = ""
        if committee_source == "Teknik":
            bucket_suffix = "-teknikmiljoe"
        elif committee_source == "Byraad":
            bucket_suffix = "-byraad"
        elif committee_source == "Plan":
            bucket_suffix = "-plan"
            
        bucket_name = f"raw-files-{muni_name}{bucket_suffix}".replace('_', '-') # S3 buckets usually dash, not underscore

        # Construct Direct Download Link
        direct_download_url = f"{base_url.rstrip('/')}/pdf/GetDagsorden/{uuid}"
        
        # S3 Remote Filename: Insert source URL before extension
        # e.g., "my_file&&https://.../foo.pdf" instead of "my_file.pdf&&https://..."
        name_root, name_ext = os.path.splitext(filename)
        # Sanitize URL: Replace '/' with '@' to avoid S3 folder creation
        sanitized_url = direct_download_url.replace('/', '@')
        remote_filename = f"{name_root}&&{sanitized_url}{name_ext}"

        # --- CHECK EXISTENCE (Cloud or Local) ---
        if IS_RENDER:
             # Check Wasabi first
             s3 = scraper_utils.get_s3_client()
             try:
                 # Check for the remote filename (which includes the URL)
                 s3.head_object(Bucket=bucket_name, Key=remote_filename)
                 print(f"     Skipping {remote_filename} (Already in Wasabi)")
                 return
             except:
                 pass
        elif os.path.exists(local_path):
             # print(f"     Skipping (Exists): {filename}")
             return


        print(f"     Downloading: {filename} ...")
        
        # Snapshot for detection
        files_before = set(glob(os.path.join(download_dir, "*.pdf")))
        
        try:
            driver.get(direct_download_url)
        except Exception as e:
            print(f"     > Browser error: {e}")
            return

        # Wait for file
        timeout = time.time() + 60
        downloaded_file = None

        while time.time() < timeout:
            files_now = set(glob(os.path.join(download_dir, "*.pdf")))
            new_files = files_now - files_before

            if new_files:
                potential_file = new_files.pop()
                if not potential_file.endswith(".crdownload"):
                    downloaded_file = potential_file
                    break
            time.sleep(0.5)

        # Rename & Upload
        if downloaded_file:
            try:
                time.sleep(1)  # Release handle
                # Move to final name
                if os.path.exists(local_path):
                    os.remove(local_path) # Overwrite if exists (locally)
                os.rename(downloaded_file, local_path)
                
                # --- UPLOAD IF ON RENDER ---
                if IS_RENDER:
                    # Upload using the new remote_filename
                    scraper_utils.upload_to_wasabi(local_path, bucket_name, remote_filename)
                    if os.path.exists(local_path):
                        os.remove(local_path)
                else:
                    print(f"     > Success!")
                    
            except Exception as e:
                print(f"     > Error renaming/uploading: {e}")
        else:
            print("     > Timeout waiting for file.")

    except Exception as e:
        print(f"     Error processing URL: {e}")


def get_municipalities_from_file(input_file):
    """Reads the CSV file and returns a list of dicts."""
    municipalities = []
    try:
        # Try reading with pandas if available (more robust CSV parsing)
        df = pd.read_csv(input_file)
        for _, row in df.iterrows():
            municipalities.append({
                'base_url': row['Base URL'].strip(),
                'start_url': row['Start URL'].strip()
            })
    except Exception:
        # Fallback to standard CSV
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                municipalities.append({
                    'base_url': row['Base URL'].strip(),
                    'start_url': row['Start URL'].strip()
                })
    return municipalities


def extract_name_from_url(url):
    """Extracts 'esbjerg' from 'https://dagsordener.esbjergkommune.dk'"""
    domain = urlparse(url).netloc
    # Remove 'dagsordener.' and '.dk'
    name = domain.replace('dagsorden.', '').replace('dagsordener.', '').replace('.dk', '')
    # Remove 'kommune' if present to keep it short
    name = name.replace('kommune', '')
    return name


# --- MAIN ORCHESTRATOR ---
def run_scraper():
    print(f"--- Starting Multi-Municipality Scraper ---")
    
    # Determine which sources to run
    env_source = os.environ.get('COMMITTEE_SOURCE')
    sources_to_run = {}
    
    if env_source:
        if env_source in COMMITTEE_CONFIGS:
             sources_to_run[env_source] = COMMITTEE_CONFIGS[env_source]
        else:
             print(f"Warning: Unknown COMMITTEE_SOURCE '{env_source}'. Valid: {list(COMMITTEE_CONFIGS.keys())}")
             return
    else:
        sources_to_run = COMMITTEE_CONFIGS

    print(f"Sources to run: {list(sources_to_run.keys())}")
    print(f"Download Limit: {MAX_DOWNLOADS if MAX_DOWNLOADS else 'Unlimited'}")

    for source_name, input_file in sources_to_run.items():
        print(f"\n=== Processing Source: {source_name} ===")
        print(f"Reading from: {input_file}")

        targets = get_municipalities_from_file(input_file)
        print(f"Found {len(targets)} municipalities to process.\n")

    for target in targets:
        base_url = target['base_url']
        start_url = target['start_url']

        # Generate a folder name based on the URL (e.g., raw_files_esbjerg)
        muni_name = extract_name_from_url(base_url)
        
        # --- APPLY FILTER IF SET ---
        municipality_filter_env = os.environ.get("MUNICIPALITY_FILTER")
        if municipality_filter_env:
            # Split and check if ANY filter matches
            filters = [f.strip().lower() for f in municipality_filter_env.split(",") if f.strip()]
            
            # Check if this municipality matches ANY of the filters
            if not any(f in muni_name.lower() for f in filters):
                # print(f"Skipping {muni_name} (Does not match filters: {filters})")
                continue

        # Modify local folder name based on committee source
        dir_suffix = ""
        if source_name == "Teknik":
            dir_suffix = "_teknikmiljoe"
        elif source_name == "Byraad":
            dir_suffix = "_byraad"
        elif source_name == "Plan":
            dir_suffix = "_plan"

        download_dir = os.path.abspath(f"raw_files_{muni_name}{dir_suffix}")
        os.makedirs(download_dir, exist_ok=True)

            print(f"[*] Processing: {muni_name.upper()} ({source_name})")
            print(f"    Folder: {download_dir}")

            # Start a fresh driver for this municipality to ensure clean download folder
            driver = get_driver(download_dir)

            try:
                # 1. Get Links
                meeting_links = get_meeting_links(driver, start_url, base_url)

                if not meeting_links:
                    print("    No links found. Skipping.")
                    continue

                # Apply limit if set
                if MAX_DOWNLOADS:
                    meeting_links = meeting_links[:MAX_DOWNLOADS]

                print(f"    Processing {len(meeting_links)} files...")

                # 2. Download Loop
                for i, link in enumerate(meeting_links):
                    print(f"    [{i + 1}/{len(meeting_links)}]", end="")
                    process_download(driver, link, base_url, download_dir, muni_name, source_name)

            except Exception as e:
                print(f"    Critical error for {muni_name}: {e}")
            finally:
                driver.quit()

            print(f"    Finished {muni_name} ({source_name}).\n")

    print("--- All Jobs Complete ---")


if __name__ == "__main__":
    run_scraper()