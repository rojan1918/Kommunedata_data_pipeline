import os
import re
import time
import base64
import json
import platform
import datetime
import scraper_utils
from urllib.parse import urljoin
from bs4 import BeautifulSoup

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
START_URL = 'https://ishoj.dk/borger/demokrati/dagsordener-og-referater/'
WASABI_BUCKET = "raw-files-ishoej" 

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('referater_ishoj_local')
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
    chrome_options.add_argument("--remote-debugging-port=9222")
    
    # 3. USER AGENT (Cloudflare Bypassing)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 4. RENDER SPECIFIC
    if IS_RENDER:
        chrome_options.add_argument("--headless=new")
        chrome_options.binary_location = "/usr/bin/chromium"

    # 5. PRINTING PREFS
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
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


def get_meeting_links(driver):
    print(f"Accessing: {START_URL}")
    driver.get(START_URL)

    # --- 1. WAIT FOR CLOUDFLARE TO CLEAR ---
    print("Waiting 10s for Cloudflare/Page Load...")
    time.sleep(10)

    print(f"Current Page Title: '{driver.title}'")

    # If we are stuck on Cloudflare, wait longer
    if "øjeblik" in driver.title.lower() or "just a moment" in driver.title.lower():
        print("!!! Cloudflare challenge detected. Waiting 20 more seconds for auto-solve...")
        time.sleep(20)

    # --- 2. PARSE HTML ---
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # Find the button. We search for "Planudvalget" to avoid 'Ø' encoding issues.
    # We look for the BUTTON tag specifically.
    target_button = soup.find('button', class_='accordion-item-header', string=re.compile(r"Planudvalget"))

    if not target_button:
        print("Error: Could not find 'Økonomi- og Planudvalget' section.")

        # --- DEBUG: SAVE HTML TO SEE WHAT WENT WRONG ---
        with open("debug_failure.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(">>> SAVED 'debug_failure.html'. Please open this file to see what the script saw.")
        return []

    print("Found Committee Button. Extracting links...")
    links = []

    # 3. FIND CONTENT DIV
    # HTML Structure:
    # <h4 class="accordion-item-title"><button>...</button></h4>
    # <div class="accordion-item-content">...</div>

    header_parent = target_button.find_parent('h4')
    if header_parent:
        content_div = header_parent.find_next_sibling('div', class_='accordion-item-content')
        if content_div:
            anchors = content_div.find_all('a')
            for a in anchors:
                href = a.get('href')
                if href:
                    full_url = urljoin(START_URL, href)
                    links.append(full_url)

    print(f"Found {len(links)} meeting links.")
    return links


def process_meeting(driver, url):
    try:
        # Extract date for filename (e.g., 18-08-2025)
        date_match = re.search(r'(\d{2}-\d{2}-\d{4})', url)
        date_obj = None
        if date_match:
            d_str, m_str, y_str = date_match.group(1).split('-')
            filename = f"{y_str}-{m_str}-{d_str}_ishoj_oekonomiudvalget.pdf"
            try:
                date_obj = datetime.date(int(y_str), int(m_str), int(d_str))
            except:
                pass
        else:
            filename = f"ishoj_{url.split('/')[-1][:20]}.pdf"

        # --- DATE FILTERING ---
        if date_obj and not scraper_utils.should_scrape(date_obj):
             # print(f"Skipping {filename} (Filtered by Date)")
             return

        local_path = os.path.join(DOWNLOAD_DIR, filename)

        # --- CHECK IF EXISTS (Cloud or Local) ---
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
        driver.get(url)
        time.sleep(3)  # Wait for load

        # 4. FORCE OPEN ACCORDIONS (CSS INJECTION)
        # We inject CSS to force everything visible, bypassing clicks entirely.
        driver.execute_script("""
            // Force display block on all hidden accordions
            var style = document.createElement('style');
            style.innerHTML = `
                .accordion-item-content { 
                    display: block !important; 
                    height: auto !important; 
                    opacity: 1 !important; 
                    visibility: visible !important; 
                }
                .main-nav, .main-header, .search-panel, .main-footer, #CookieConsent, .mobile-nav { 
                    display: none !important; 
                } 
                .main { width: 100% !important; max-width: 100% !important; }
            `;
            document.head.appendChild(style);

            // Nuke cookie banner elements by ID just in case
            var badIds = ['CookieConsent', 'Cookiebot', 'cookie-consent-banner'];
            badIds.forEach(id => { var el = document.getElementById(id); if(el) el.remove(); });
        """)
        time.sleep(1)

        # 5. PRINT TO PDF
        try:
            result = driver.execute_cdp_cmd("Page.printToPDF", {
                "landscape": False,
                "displayHeaderFooter": False,
                "printBackground": True,
                "preferCSSPageSize": True,
            })
            
            with open(local_path, 'wb') as f:
                f.write(base64.b64decode(result['data']))
            
            # --- UPLOAD IF ON RENDER ---
            if IS_RENDER:
                scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
                if os.path.exists(local_path):
                    os.remove(local_path)
            else:
                print("   > Saved locally.")

        except Exception as e:
            print(f"   > Error printing/saving PDF: {e}")

    except Exception as e:
        print(f"Error processing meeting: {e}")


def run_ishoej_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return
    
    try:
        links = get_meeting_links(driver)

        if links:
            print(f"Starting download of {len(links)} files...")
            for i, link in enumerate(links):
                print(f"[{i + 1}/{len(links)}]", end=" ")
                process_meeting(driver, link)
        else:
            print("No links found. Check debug_failure.html.")

    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        driver.quit()
        print("\n--- Done ---")


if __name__ == "__main__":
    run_ishoej_scraper()