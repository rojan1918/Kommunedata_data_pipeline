import os
import time
import re
import base64
import json
import platform
import datetime
import scraper_utils

# --- LIBRARIES ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Error: Selenium library not found.")
    exit()

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_URL = "https://www.rk.dk"
START_URL = "https://www.rk.dk/politik/politiske-udvalg/oekonomiudvalget"
WASABI_BUCKET = "raw-files-roedovre"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_roedovre')
    print(f"--- RUNNING LOCALLY ---")

# --- SETUP SELENIUM (FIXED) ---
def get_driver():
    chrome_options = Options()

    # 1. BASIC STABILITY OPTIONS
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # 2. CRASH FIX: Remote Debugging Port
    # This is often required to stop the "Chrome exited" error in Docker
    chrome_options.add_argument("--remote-debugging-port=9222")

    # 3. RENDER SPECIFIC
    if IS_RENDER:
        chrome_options.add_argument("--headless=new")
        # Explicitly point to the chromium binary installed by apt-get
        chrome_options.binary_location = "/usr/bin/chromium"

    # 4. PRINTING PREFS
    settings = {
        "recentDestinations": [{"id": "Save as PDF", "origin": "local", "account": ""}],
        "selectedDestinationId": "Save as PDF",
        "version": 2
    }
    prefs = {
        'printing.print_preview_sticky_settings.appState': json.dumps(settings),
        'savefile.default_directory': DOWNLOAD_DIR
    }
    chrome_options.add_experimental_option('prefs', prefs)

    print(f"Starting Chrome...")
    if IS_RENDER:
        print(f"   Binary: /usr/bin/chromium")

    try:
        # We do NOT pass 'executable_path' manually.
        # Since we installed 'chromium-driver' via apt, it is on the system PATH.
        # Selenium Manager will find it automatically.
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- COOKIES ---
def handle_cookies(driver):
    try:
        wait = WebDriverWait(driver, 3)
        xpath = "//button[contains(text(), 'Afvis alle') or contains(text(), 'Accepter alle') or contains(text(), 'Tillad alle')]"
        button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        if button:
            driver.execute_script("arguments[0].click();", button)
            time.sleep(1)
    except:
        pass


# --- PRINT TO PDF ---
def print_page_to_pdf(driver, output_path):
    try:
        pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "displayHeaderFooter": False
        })
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(pdf_data['data']))
        return True
    except Exception as e:
        print(f"   > Error printing PDF: {e}")
        return False


# --- LOGIC ---
def get_meeting_links(driver):
    print(f"--- Getting Meeting List ---")
    driver.get(START_URL)
    handle_cookies(driver)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section.section-box .link a")))
    except:
        return []

    links = driver.find_elements(By.CSS_SELECTOR, "section.section-box .link a")
    meetings = []
    for link in links:
        href = link.get_attribute('href')
        text = link.get_attribute("textContent")
        if text and href:
            match = re.search(r"(\d{2})-(\d{2})-(\d{4})", text.strip())
            if match:
                d_str, m_str, y_str = match.groups()
                # Create date object for filtering
                try:
                    date_obj = datetime.date(int(y_str), int(m_str), int(d_str))
                    meetings.append((href, f"{y_str}-{m_str}-{d_str}", date_obj))
                except:
                    pass
    return meetings


def process_meeting(driver, meeting_url, date_str):
    filename = f"{date_str}_roedovre_oekonomiudvalget.pdf"
    local_path = os.path.join(DOWNLOAD_DIR, filename)

    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                s3.head_object(Bucket=WASABI_BUCKET, Key=filename)
                print(f"Skipping {filename} (Already in Wasabi)")
                return
            except:
                pass

    elif os.path.exists(local_path):
        print(f"Skipping {filename} (Exists locally)")
        return

    print(f"Processing: {filename} ...")
    try:
        driver.get(meeting_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
        handle_cookies(driver)

        if print_page_to_pdf(driver, local_path):
            if IS_RENDER:
                scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
                if os.path.exists(local_path):
                    os.remove(local_path)
            else:
                print("   > Saved locally.")
        else:
            print("   > Failed to print.")

    except Exception as e:
        print(f"   > Error: {e}")


def run_roedovre_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return
    try:
        meetings = get_meeting_links(driver)
        print(f"Found {len(meetings)} meetings.")
        
        for i, (url, date_str, date_obj) in enumerate(meetings):
            # Check Date Filter
            if not scraper_utils.should_scrape(date_obj):
                # print(f"Skipping {date_str} (Filtered by Date)")
                continue
                
            process_meeting(driver, url, date_str)
            
    finally:
        driver.quit()
        print("\n--- Complete! ---")


if __name__ == "__main__":
    run_roedovre_scraper()