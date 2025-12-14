import os
import time
import re
import html as html_parser
import requests
import json
import datetime
from urllib.parse import unquote

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
except ImportError:
    print("Error: Selenium not installed. Run: pip install selenium")
    exit()

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
START_URL = "https://referater.aalborg.dk/politiske-udvalg/oekonomiudvalget"
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
WASABI_BUCKET = "raw-files-aalborg"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('raw_files_aalborg')
    print(f"--- RUNNING LOCALLY ---")


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

    # 3. PRINTING PREFS
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
    
    if IS_RENDER:
        print(f"   Binary: /usr/bin/chromium")

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not IS_RENDER and not os.path.exists(driver_path):
        driver_path = 'chromedriver'
        
    service = Service(executable_path=driver_path) if not IS_RENDER else None
    
    if service:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver


def get_aalborg_meeting_links(driver):
    print(f"--- Step 1: Finding Meeting Pages on {START_URL} ---")
    driver.get(START_URL)
    time.sleep(3)

    # 1. Cookie Banner
    try:
        cookie_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//*[contains(text(), 'Tillad alle') or contains(text(), 'Accepter')]"))
        )
        cookie_btn.click()
        time.sleep(1)
    except:
        pass

    # 2. Expand all year dropdowns via JS
    print("   > Expanding all year dropdowns via JS...")
    try:
        driver.execute_script("""
            const items = document.querySelectorAll('bui-accordion-item');
            items.forEach(item => {
                item.setAttribute('expanded', '');
            });
        """)
        time.sleep(2)
    except Exception as e:
        print(f"   > JS Expansion error: {e}")

    # 3. Scrape Meeting Links
    print("   > Scraping links...")
    # Find all links containing 'moedetitel='
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='moedetitel=']")

    meeting_urls = set()
    for link in links:
        href = link.get_attribute('href')
        if href:
            meeting_urls.add(href)

    print(f"   > Found {len(meeting_urls)} unique meetings.")
    return list(meeting_urls)


def download_pdf(session, meeting_url):
    try:
        # 1. Get page content using requests (faster)
        response = session.get(meeting_url)
        response.raise_for_status()
        page_html = response.text

        # 2. Find the PDF Link using Regex
        match = re.search(r"window\.open\('([^']+)'\)", page_html)
        if not match:
            match = re.search(r"(https://apps\.aalborgkommune\.dk/aakReferater/Pdf\.aspx[^']*)", page_html)

        if not match:
            print(f"Skipping: No PDF link found on {meeting_url}")
            return False

        raw_link = match.group(1)

        # 3. Decode HTML entities (Change &amp; back to &)
        pdf_url = html_parser.unescape(raw_link)

        # 4. Generate Filename & Extract Date
        # The URL looks like: .../Pdf.aspx?pdfnavn=2024-04-08 10.30.pdf&type=moede...
        filename = "aalborg_unknown.pdf"
        date_obj = None
        
        name_match = re.search(r'pdfnavn=([^&]*)', pdf_url)
        if name_match:
            original_name = unquote(name_match.group(1))  # Decode %20 to space
            # Try to extract date YYYY-MM-DD
            date_part = re.search(r'(\d{4}-\d{2}-\d{2})', original_name)
            if date_part:
                date_str = date_part.group(1)
                filename = f"{date_str}_aalborg_oekonomiudvalget.pdf"
                try:
                    y, m, d = map(int, date_str.split('-'))
                    date_obj = datetime.date(y, m, d)
                except:
                    pass
            else:
                filename = f"aalborg_oekonomiudvalget_{original_name}"

        # Clean filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # --- DATE FILTERING ---
        if date_obj and not scraper_utils.should_scrape(date_obj):
             # print(f"Skipping {filename} (Filtered by Date)")
             return False

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

        # 5. Download
        print(f"Downloading: {filename}")
        pdf_resp = session.get(pdf_url, stream=True)
        pdf_resp.raise_for_status()

        with open(local_path, 'wb') as f:
            for chunk in pdf_resp.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # --- UPLOAD IF ON RENDER ---
        if IS_RENDER:
            scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
            if os.path.exists(local_path):
                os.remove(local_path)
        else:
            print("   > Saved locally.")
            
        return True

    except Exception as e:
        print(f"Error downloading from {meeting_url}: {e}")
        return False


def run_aalborg_scrape():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    if not driver: return
    
    try:
        # 1. Get Links
        links = get_aalborg_meeting_links(driver)
    finally:
        driver.quit()

    if not links:
        print("No links found.")
        return

    # 2. Download Files
    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    print(f"\n--- Step 2: Downloading {len(links)} PDFs ---")
    
    download_limit = scraper_utils.get_download_limit()
    processed_count = 0
    
    for i, link in enumerate(links):
        if download_limit and processed_count >= download_limit:
            print(f"Reached download limit ({download_limit}). Stopping.")
            break
            
        print(f"[{i + 1}/{len(links)}]", end=" ")
        if download_pdf(session, link):
            processed_count += 1

    print("\n--- Aalborg Scrape Complete! ---")


if __name__ == "__main__":
    run_aalborg_scrape()