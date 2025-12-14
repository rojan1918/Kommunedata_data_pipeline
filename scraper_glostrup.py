import os
import time
import re
import requests
import json
import datetime
import platform
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
BASE_URL = "https://dagsorden.glostrup.dk"
START_URL = "https://dagsorden.glostrup.dk/"
START_DATE = "01/01/2023"
WASABI_BUCKET = "raw-files-glostrup"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_glostrup')
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


# --- STEP 1: SEARCH ---
def perform_search(driver):
    print("--- Step 1: Navigating and Searching ---")
    driver.get(START_URL)
    wait = WebDriverWait(driver, 10)

    try:
        select_element = wait.until(EC.presence_of_element_located((By.ID, "searchSelect")))
        select = Select(select_element)
        print("   > Selecting 'Økonomiudvalget'...")
        select.select_by_visible_text("Økonomiudvalget")

        print(f"   > Setting Start Date to {START_DATE}...")
        date_input = driver.find_element(By.ID, "from")
        date_input.clear()
        date_input.send_keys(START_DATE)
        driver.find_element(By.TAG_NAME, "body").click()
        time.sleep(1)

        search_btn = driver.find_element(By.ID, "searchButton")
        search_btn.click()
        print("   > Clicked Search. Waiting for results...")

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#resultTable tbody tr")))
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Error during search: {e}")
        return False


# --- STEP 2: SCRAPE TABLE ---
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


# --- STEP 3: DOWNLOAD ---
def download_document(driver, meeting):
    date_str = meeting['date_str']
    meeting_url = meeting['url']
    date_obj = meeting['date_obj']

    # --- DATE FILTERING ---
    if date_obj and not scraper_utils.should_scrape(date_obj):
         # print(f"Skipping {date_str} (Filtered by Date)")
         return False

    # Filenames (we support PDF or DOCX)
    filename_base = f"{date_str}_glostrup_oekonomiudvalget"
    
    # Check if ANY file for this date exists in Wasabi
    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                # Check for PDF
                s3.head_object(Bucket=WASABI_BUCKET, Key=f"{filename_base}.pdf")
                print(f"Skipping {filename_base}.pdf (Already in Wasabi)")
                return True
            except:
                try:
                    # Check for DOCX
                    s3.head_object(Bucket=WASABI_BUCKET, Key=f"{filename_base}.docx")
                    print(f"Skipping {filename_base}.docx (Already in Wasabi)")
                    return True
                except:
                    pass
    else:
        # Local check
        if os.path.exists(os.path.join(DOWNLOAD_DIR, f"{filename_base}.pdf")):
             return True
        if os.path.exists(os.path.join(DOWNLOAD_DIR, f"{filename_base}.docx")):
             return True

    print(f"Processing: {meeting_url} ...")

    try:
        driver.get(meeting_url)
        wait = WebDriverWait(driver, 10)

        button = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@data-id and contains(@onclick, 'download')]")
        ))

        file_id = button.get_attribute('data-id')
        file_name = button.get_attribute('data-name')

        if file_id and file_name:
            doc_url = f"{BASE_URL}/meeting/files/{file_id}/{file_name}"

            resp = requests.get(doc_url, stream=True)
            resp.raise_for_status()

            content_type = resp.headers.get('Content-Type', '').lower()
            
            # Determine extension
            if 'pdf' in content_type or file_name.endswith('.pdf'):
                final_filename = f"{filename_base}.pdf"
            else:
                final_filename = f"{filename_base}.docx"

            final_path = os.path.join(DOWNLOAD_DIR, final_filename)

            print(f"   > Downloading {final_filename}...")
            with open(final_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # --- UPLOAD IF ON RENDER ---
            if IS_RENDER:
                scraper_utils.upload_to_wasabi(final_path, WASABI_BUCKET, final_filename)
                if os.path.exists(final_path):
                    os.remove(final_path)
            else:
                print("   > Saved locally.")
                
            return True

        else:
            print(f"   > Skipped: Button attributes missing.")
            return False

    except TimeoutException:
        print(f"   > Skipped: Download button not found.")
        return False
    except Exception as e:
        print(f"   > Error: {e}")
        return False


# --- MAIN ---
def run_glostrup_scraper():
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

        print(f"\n--- Step 3: Downloading {len(meetings)} Documents ---")
        
        download_limit = scraper_utils.get_download_limit()
        processed_count = 0
        
        for i, meeting in enumerate(meetings):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            if download_document(driver, meeting):
                processed_count += 1
                
    finally:
        driver.quit()
        print("\n--- Glostrup Scrape Complete! ---")


if __name__ == "__main__":
    run_glostrup_scraper()