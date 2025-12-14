import os
import time
import re
import requests
import json
import datetime
import scraper_utils
from urllib.parse import urljoin

# --- LIBRARIES ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
except ImportError:
    print("Error: Selenium library not found. Run: pip install selenium")
    exit()

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_URL = "https://aabendagsorden.syddjurs.dk"
START_URL = "https://aabendagsorden.syddjurs.dk/"
START_DATE = "01/01/2023"
WASABI_BUCKET = "raw-files-syddjurs"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_syddjurs')
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

    if IS_RENDER:
        print(f"   Binary: /usr/bin/chromium")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- STEP 1: PERFORM SEARCH ---
def perform_search(driver):
    print("--- Step 1: Navigating and Searching ---")
    driver.get(START_URL)
    wait = WebDriverWait(driver, 10)

    try:
        # 1. Select Committee
        select_element = wait.until(EC.presence_of_element_located((By.ID, "searchSelect")))
        select = Select(select_element)
        print("   > Selecting 'Økonomiudvalget (ØK)'...")
        select.select_by_visible_text("Økonomiudvalget (ØK)")

        # 2. Set Start Date (NEW STEP)
        print(f"   > Setting Start Date to {START_DATE}...")
        date_input = driver.find_element(By.ID, "from")
        date_input.clear()
        date_input.send_keys(START_DATE)
        # Sometimes clicking away helps close the datepicker popup
        driver.find_element(By.TAG_NAME, "body").click()
        time.sleep(1)

        # 3. Click "Søg"
        search_btn = driver.find_element(By.ID, "searchButton")
        search_btn.click()
        print("   > Clicked Search. Waiting for results...")

        # 4. Wait for table to load
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#resultTable tbody tr")))
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Error during search: {e}")
        return False


# --- STEP 2: SCRAPE TABLE (WITH PAGINATION) ---
def get_meeting_links(driver):
    print("--- Step 2: Scraping Meeting Links ---")

    all_meetings = []
    seen_urls = set()

    while True:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "#resultTable tbody tr")
            print(f"   > Processing {len(rows)} rows on current page...")

            for row in rows:
                try:
                    if "Ingen data" in row.text:
                        print("   > No data found.")
                        return all_meetings

                    cols = row.find_elements(By.TAG_NAME, "td")
                    if not cols: continue

                    date_text = cols[0].text.strip()
                    date_match = re.search(r"(\d{2}-\d{2}-\d{4})", date_text)
                    if not date_match: continue

                    clean_date = date_match.group(1)
                    d, m, y = clean_date.split('-')
                    iso_date = f"{y}-{m}-{d}"
                    date_obj = datetime.date(int(y), int(m), int(d))

                    link_el = row.find_element(By.CSS_SELECTOR, "a.row-link")
                    href = link_el.get_attribute('href')

                    if href and href not in seen_urls:
                        all_meetings.append({
                            "url": href,
                            "date_str": iso_date,
                            "date_obj": date_obj
                        })
                        seen_urls.add(href)

                except StaleElementReferenceException:
                    continue

            # Pagination
            try:
                next_li = driver.find_element(By.ID, "resultTable_next")
                classes = next_li.get_attribute("class")

                if "disabled" in classes:
                    print("   > Reached the last page.")
                    break

                next_link = next_li.find_element(By.TAG_NAME, "a")
                driver.execute_script("arguments[0].click();", next_link)
                time.sleep(2)

            except NoSuchElementException:
                print("   > No pagination found.")
                break

        except Exception as e:
            print(f"Error during pagination: {e}")
            break

    print(f"   > Found {len(all_meetings)} total meetings.")
    return all_meetings


# --- STEP 3: DOWNLOAD PDF (SELENIUM ENABLED) ---
def download_pdf(driver, meeting):
    date_str = meeting['date_str']
    meeting_url = meeting['url']
    date_obj = meeting['date_obj']

    # --- DATE FILTERING ---
    if date_obj and not scraper_utils.should_scrape(date_obj):
         # print(f"Skipping {date_str} (Filtered by Date)")
         return False

    filename = f"{date_str}_syddjurs_oekonomiudvalget.pdf"
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

    print(f"Processing: {filename} ...")

    try:
        driver.get(meeting_url)
        wait = WebDriverWait(driver, 10)

        button = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@data-id and contains(@onclick, 'download')]")
        ))

        file_id = button.get_attribute('data-id')
        file_name = button.get_attribute('data-name')

        if file_id and file_name:
            pdf_url = f"{BASE_URL}/meeting/files/{file_id}/{file_name}"

            print(f"   > Downloading...")
            resp = requests.get(pdf_url, stream=True)
            resp.raise_for_status()

            with open(local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # --- UPLOAD IF ON RENDER ---
            if IS_RENDER:
                scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
                if os.path.exists(local_path):
                    os.remove(local_path)
            else:
                print("   > Saved locally.")
                
            return True
        else:
            print(f"   > Skipped: Button found but attributes missing.")
            return False

    except TimeoutException:
        print(f"   > Skipped: Download button not loaded/found on page.")
        return False
    except Exception as e:
        print(f"   > Error: {e}")
        return False


# --- MAIN ---
def run_syddjurs_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    if not driver: return

    try:
        if not perform_search(driver):
            return

        meetings = get_meeting_links(driver)

        if not meetings:
            print("No meetings found.")
            return

        print(f"\n--- Step 3: Downloading {len(meetings)} PDFs ---")
        
        download_limit = scraper_utils.get_download_limit()
        processed_count = 0
        
        for i, meeting in enumerate(meetings):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            if download_pdf(driver, meeting):
                processed_count += 1
                
    finally:
        driver.quit()
        print("\n--- Syddjurs Scrape Complete! ---")


if __name__ == "__main__":
    run_syddjurs_scraper()