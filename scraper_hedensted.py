import os
import time
import re
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
DOWNLOAD_DIR = os.path.abspath('raw_files_hedensted')
START_URL = "https://www.hedensted.dk/politik-og-indflydelse/kommunalbestyrelse-og-udvalg/dagsordener-og-referater/oekonomiudvalget-dagsordener-og-referater#agenda7560"
BASE_URL = "https://www.hedensted.dk"
WASABI_BUCKET = "raw-files-hedensted"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_hedensted')
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


# --- STEP 1: FIND MEETING LINKS ---
def get_meeting_links(driver):
    print(f"--- Step 1: Scraping Meeting List ---")
    driver.get(START_URL)
    time.sleep(2)  # Wait for initial load

    # 1. FORCE OPEN THE ACCORDION
    try:
        print("   > Locating accordion 'agenda7560'...")
        wait = WebDriverWait(driver, 10)
        accordion_container = wait.until(EC.presence_of_element_located((By.ID, "agenda7560")))
        header_btn = accordion_container.find_element(By.CLASS_NAME, "js-accordion-header")
        is_expanded = header_btn.get_attribute("aria-expanded")

        if is_expanded != "true":
            print("   > Accordion is closed. Clicking to open...")
            driver.execute_script("arguments[0].click();", header_btn)
            time.sleep(2)  # Wait for list to render
        else:
            print("   > Accordion is already open.")

    except Exception as e:
        print(f"   > Warning: Issue interacting with accordion: {e}")

    # 2. SCRAPE THE LINKS
    try:
        links_selector = "#agenda7560 .list__links a.list__link"
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, links_selector)))
        link_elements = driver.find_elements(By.CSS_SELECTOR, links_selector)
    except TimeoutException:
        print("Error: No links found inside #agenda7560.")
        return []

    meetings = []

    for el in link_elements:
        href = el.get_attribute('href')
        if not href: continue

        # Extract date from URL
        # Pattern: .../dagsorden/Oekonomiudvalget_2022/10-11-2025...
        match = re.search(r"/(\d{2}-\d{2}-\d{4})", href)
        date_str = None
        date_obj = None

        if match:
            date_raw = match.group(1)
            d, m, y = date_raw.split('-')
            date_str = f"{y}-{m}-{d}"
            try:
                date_obj = datetime.date(int(y), int(m), int(d))
            except:
                pass
        
        if date_str:
            meetings.append({
                "url": href, 
                "date_str": date_str,
                "date_obj": date_obj
            })

    print(f"  > Found {len(meetings)} valid meeting links.")
    return meetings


# --- STEP 2: DOWNLOAD PDF ---
def download_pdf(driver, meeting):
    date_str = meeting['date_str']
    meeting_url = meeting['url']
    date_obj = meeting['date_obj']

    # --- DATE FILTERING ---
    if date_obj and not scraper_utils.should_scrape(date_obj):
         # print(f"Skipping {date_str} (Filtered by Date)")
         return False

    filename = f"{date_str}_hedensted_oekonomiudvalget.pdf"
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

    driver.get(meeting_url)

    try:
        wait = WebDriverWait(driver, 5)
        button = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn__link.attachment-link")))

        pdf_href = button.get_attribute('href')
        if not pdf_href: return False

        if pdf_href.startswith("/"):
            pdf_url = BASE_URL + pdf_href
        else:
            pdf_url = pdf_href

        print(f"Downloading: {filename} ...")

        files_before = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))

        # downloads the file
        driver.get(pdf_url)

        timeout = time.time() + 30
        while time.time() < timeout:
            files_now = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
            new_files = files_now - files_before

            if new_files:
                new_file = new_files.pop()
                if not new_file.endswith(".crdownload"):
                    time.sleep(1)
                    # If local file exists, remove
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
        print(f"  > Skipped: No PDF found on {meeting_url}")
        return False
    except Exception as e:
        print(f"  > Error: {e}")
        return False


# --- MAIN ---
def run_hedensted_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return

    try:
        links = get_meeting_links(driver)

        print(f"\n--- Step 2: Downloading {len(links)} PDFs ---")
        
        download_limit = scraper_utils.get_download_limit()
        processed_count = 0
        
        for i, meeting in enumerate(links):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(links)}]", end=" ")
            if download_pdf(driver, meeting):
                processed_count += 1
                
    finally:
        driver.quit()
        print("\n--- Hedensted Scrape Complete! ---")


if __name__ == "__main__":
    run_hedensted_scraper()
