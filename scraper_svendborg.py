import os
import re
import time
import base64
import json
import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# --- UTILS ---
import scraper_utils

# --- LIBRARIES ---
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Error: Selenium library not found.")
    exit()

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_URL = "https://www.svendborg.dk/dagsordener-og-referater/?committees=8968"
DOMAIN = "https://www.svendborg.dk"
WASABI_BUCKET = "raw-files-svendborg"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('referater_svendborg')
    print(f"--- RUNNING LOCALLY ---")


def get_driver():
    print("Initializing Browser...")
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
        # Local Headless? Or visible? Let's default to headless to match 'scraper.py' logic
        # but the original script had 'headless=new' commented out or conditional.
        # User wants consistent behavior.
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
        
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


def get_all_meeting_links(driver):
    print(f"--- Step 1: Finding meetings from {BASE_URL} ---")

    all_meetings = []
    offset = 0
    page_size = 12  # Svendborg loads 12 items per "Vis flere"
    
    # Limit Logic
    download_limit = scraper_utils.get_download_limit()
    
    while True:
        # Construct paginated URL
        if offset == 0:
            current_url = BASE_URL
        else:
            current_url = f"{BASE_URL}&o0={offset}"

        print(f"  > Scanning offset {offset}...")
        try:
            driver.get(current_url)
            # Wait for list to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "c-list-item"))
            )

            # Parse HTML
            soup = BeautifulSoup(driver.page_source, 'html.parser')

            # Find all list items
            items = soup.find_all("li", class_="c-list-item")

            if not items:
                print("    No items found on this page. Stopping.")
                break

            found_new = 0
            for item in items:
                # 1. Check Type (Dagsorden vs Referat)
                type_span = item.find("span", class_="text-caption-md-regular")
                if not type_span or "referat" not in type_span.get_text(strip=True).lower():
                    continue

                # 2. Extract Link
                link = item.find("a", class_="c-list-item__title")
                if not link: continue

                href = link.get('href')
                full_url = urljoin(DOMAIN, href)

                # 3. Extract Date
                date_span = item.find("span", class_="text-caption-md-strong")
                date_text = date_span.get_text(strip=True) if date_span else "0000"
                
                # 4. Create Filename & Date Object
                date_obj = None
                try:
                    date_match = re.search(r"(\d+)\.\s+([a-z]+)\s+(\d{4})", date_text.lower())
                    if date_match:
                        day, month_name, year = date_match.groups()
                        months = {
                            'januar': '01', 'februar': '02', 'marts': '03', 'april': '04',
                            'maj': '05', 'juni': '06', 'juli': '07', 'august': '08',
                            'september': '09', 'oktober': '10', 'november': '11', 'december': '12'
                        }
                        m = months.get(month_name, '01')
                        filename = f"{year}-{m}-{day.zfill(2)}_svendborg_oekonomiudvalget.pdf"
                        date_obj = datetime.date(int(year), int(m), int(day))
                    else:
                        filename = f"svendborg_referat_{offset}.pdf"
                except:
                    filename = f"svendborg_referat_{offset}.pdf"

                # Deduplication check
                if not any(m['url'] == full_url for m in all_meetings):
                    all_meetings.append({
                        "url": full_url,
                        "filename": filename,
                        "date_obj": date_obj
                    })
                    found_new += 1
            
            print(f"    Found {found_new} referater on this page.")

            if found_new == 0 and offset > 36:
                print("    End of content reached.")
                break

            offset += page_size
            
            # Optimization: If we have limit, and we found enough meetings (ignoring date filter for now or precise filtering?)
            # The user says "limit overrides date filter" -> "not matter the date filter if Limit is 1 it only takes one file".
            # This implies we can stop collecting links if we have enough CANDIDATES.
            # But wait, we might need to filter by date first? 
            # "Also i would not only like to filter by date but also set a limit"
            # Logic: Collect, then Filter, then Limit.
            # BUT efficient scraping means we should stop if we have enough VALID files.
            # Since we have dates, we can check date filter here.
            
            if download_limit:
                 # Count valid meetings so far
                 valid_count = 0
                 for m in all_meetings:
                     if m['date_obj'] and scraper_utils.should_scrape(m['date_obj']):
                         valid_count += 1
                 
                 if valid_count >= download_limit:
                     print(f"    Reached limit of {download_limit} valid files.")
                     break

        except Exception as e:
            print(f"    Error on offset {offset}: {e}")
            break

    return all_meetings


def process_meeting(driver, meeting):
    filename = meeting['filename']
    url = meeting['url']
    date_obj = meeting.get('date_obj')

    # --- DATE FILTERING ---
    if date_obj and not scraper_utils.should_scrape(date_obj):
        # print(f"Skipping {filename} (Filtered by Date)")
        return False # Did not process

    local_path = os.path.join(DOWNLOAD_DIR, filename)

    # --- CHECK IF EXISTS (Cloud or Local) ---
    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                s3.head_object(Bucket=WASABI_BUCKET, Key=filename)
                print(f"Skipping {filename} (Already in Wasabi)")
                return True # Count as processed/success
            except:
                pass
    elif os.path.exists(local_path):
        print(f"Skipping {filename} (Exists locally)")
        return True

    print(f"Processing: {filename} ...")
    try:
        driver.get(url)
        time.sleep(3)  # Wait for content to load

        # --- CLEANUP DOM FOR PDF ---
        # Hides header, footer, buttons, cookie banner
        driver.execute_script("""
            var ids = ['CookieConsent', 'coiOverlay', 'cookie-information-template-wrapper'];
            ids.forEach(id => { var el = document.getElementById(id); if(el) el.remove(); });

            var classesToHide = [
                'c-site-header',      // Top menu
                'c-site-footer',      // Footer
                'c-page-module-bar',  // Bottom floating bar
                'c-floating-sidebar', // Right sidebar
                'c-skip-to-content',  // Skip links
                'c-base-button',      // Hide ALL buttons (including Print)
                'c-horizontal-collapser' // Breadcrumbs
            ];

            classesToHide.forEach(cls => {
                var els = document.getElementsByClassName(cls);
                for(var i=0; i<els.length; i++) els[i].style.display = 'none';
            });

            var main = document.getElementById('main');
            if(main) {
                main.style.maxWidth = '100%';
                main.style.margin = '0';
                main.style.padding = '20px';
            }
        """)
        time.sleep(1)

        # --- PRINT TO PDF ---
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
            
        return True # Processed successfully

    except Exception as e:
        print(f"Error saving PDF: {e}")
        return False


def run_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return

    try:
        meetings = get_all_meeting_links(driver)
        print(f"Total meetings found: {len(meetings)}")
        
        # Apply Limit Logic Here as well
        download_limit = scraper_utils.get_download_limit()
        processed_count = 0

        for i, meeting in enumerate(meetings):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            if process_meeting(driver, meeting):
                processed_count += 1

    finally:
        driver.quit()
        print("\n--- Done! ---")


if __name__ == "__main__":
    run_scraper()