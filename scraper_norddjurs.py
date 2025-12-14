import os
import time
import re
import json
import datetime
from glob import glob

# --- UTILS ---
import scraper_utils

# --- LIBRARIES ---
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

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
START_URL = "https://norddjurs.meetingsplus.dk/committees/okonomiudvalget"
BASE_URL = "https://norddjurs.meetingsplus.dk"
WASABI_BUCKET = "raw-files-norddjurs"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_norddjurs')
    print(f"--- RUNNING LOCALLY ---")


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    
    # 1. BASIC STABILITY OPTIONS
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--remote-debugging-port=9222")
    
    # 2. RENDER SPECIFIC
    if IS_RENDER:
        chrome_options.add_argument("--headless=new")
        chrome_options.binary_location = "/usr/bin/chromium"
    else:
        chrome_options.add_argument("--headless=new")

    # Force download to our folder
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if IS_RENDER:
        print(f"   Binary: /usr/bin/chromium")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- STEP 1: FIND MEETING LINKS AND DATES ---
def get_meeting_info(driver):
    print(f"--- Step 1: Scraping Meeting List from {START_URL} ---")
    driver.get(START_URL)

    # Wait for the Recent Content container
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "committeesRecentContent"))
        )
    except TimeoutException:
        print("Error: Could not load meeting list.")
        return []

    # Find all rows in the recent content
    links = driver.find_elements(By.CSS_SELECTOR, "#committeesRecentContent a.accessible-table-cell")

    meetings = []  # List of dicts
    seen_urls = set()

    for link in links:
        href = link.get_attribute('href')
        text = link.text

        # Skip duplicates or invalid links
        if not href or href in seen_urls:
            continue

        # Extract Date from text (e.g., "2025-11-04")
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        date_str = None
        
        if date_match:
            date_str = date_match.group(1)
        else:
            # Fallback: Try to get date from aria-label
            aria = link.get_attribute("aria-label")
            date_match_aria = re.search(r"(\d{4}-\d{2}-\d{2})", aria if aria else "")
            if date_match_aria:
                date_str = date_match_aria.group(1)
        
        if date_str:
            try:
                y, m, d = map(int, date_str.split('-'))
                date_obj = datetime.date(y, m, d)
                
                meetings.append({
                    "url": href, 
                    "date_str": date_str,
                    "date_obj": date_obj
                })
                seen_urls.add(href)
            except:
                pass

    print(f"  > Found {len(meetings)} unique meetings with dates.")
    return meetings


# --- STEP 2: DOWNLOAD PDF ---
def download_meeting_pdf(driver, meeting):
    date_str = meeting['date_str']
    meeting_url = meeting['url']
    date_obj = meeting['date_obj']

    # --- DATE FILTERING ---
    if date_obj and not scraper_utils.should_scrape(date_obj):
         # print(f"Skipping {date_str} (Filtered by Date)")
         return False

    # 1. Generate Filename
    filename = f"{date_str}_norddjurs_oekonomiudvalget.pdf"
    local_path = os.path.join(DOWNLOAD_DIR, filename)

    # --- CHECK IF EXISTS (Cloud or Local) ---
    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                s3.head_object(Bucket=WASABI_BUCKET, Key=filename)
                print(f"Skipping {filename} (Already in Wasabi)")
                return True # Count as processed
            except:
                pass
    elif os.path.exists(local_path):
        # print(f"Skipping (Exists): {filename}")
        return True

    # 2. Visit Meeting Page
    driver.get(meeting_url)

    try:
        # 3. Find 'Vis referat' button by ID 'openProtocol'
        wait = WebDriverWait(driver, 5)
        button = wait.until(EC.presence_of_element_located((By.ID, "openProtocol")))

        pdf_url = button.get_attribute('href')

        # OPTIONAL: Change 'downloadMode=open' to 'downloadMode=download' to be safe
        if "downloadMode=open" in pdf_url:
            pdf_url = pdf_url.replace("downloadMode=open", "downloadMode=download")

        print(f"Downloading: {filename} ...")

        # 4. Snapshot files before download
        files_before = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))

        # 5. Trigger Download
        driver.get(pdf_url)

        # 6. Wait for file
        timeout = time.time() + 60
        while time.time() < timeout:
            files_now = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
            new_files = files_now - files_before

            if new_files:
                new_file = new_files.pop()
                # Wait if it's still a temp file
                if not new_file.endswith(".crdownload"):
                    # Rename
                    time.sleep(1)  # Release lock
                    # If target exists locally (unlikely due to check above), remove it
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        
                    os.rename(new_file, local_path)
                    
                    # --- UPLOAD IF ON RENDER ---
                    if IS_RENDER:
                        scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
                        if os.path.exists(local_path):
                            os.remove(local_path)
                    else:
                        print("  > Success!")
                        
                    return True
            time.sleep(0.5)

        print("  > Error: Timeout waiting for file.")
        return False

    except TimeoutException:
        print(f"  > Skipped: No 'Vis referat' (openProtocol) button found on {meeting_url}")
        return False
    except Exception as e:
        print(f"  > Error: {e}")
        return False


# --- MAIN ---
def run_norddjurs_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return

    try:
        # 1. Get list of meetings + dates
        meetings_data = get_meeting_info(driver)

        # 2. Process downloads
        print(f"\n--- Step 2: Downloading {len(meetings_data)} PDFs ---")
        
        download_limit = scraper_utils.get_download_limit()
        processed_count = 0
        
        for i, meeting in enumerate(meetings_data):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(meetings_data)}]", end=" ")
            if download_meeting_pdf(driver, meeting):
                processed_count += 1
                
    finally:
        driver.quit()
        print("\n--- Norddjurs Scrape Complete! ---")


if __name__ == "__main__":
    run_norddjurs_scraper()