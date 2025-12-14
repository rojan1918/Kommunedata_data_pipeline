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
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Error: Selenium library not found. Run: pip install selenium")
    exit()

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_URL = "https://middelfart.bcdagsorden.dk"
WASABI_BUCKET = "raw-files-middelfart"

if IS_RENDER:
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    DOWNLOAD_DIR = os.path.abspath('referater_middelfart')
    print(f"--- RUNNING LOCALLY ---")


def get_driver():
    print("Initializing Headless Browser...")
    chrome_options = Options()
    
    # 1. BASIC STABILITY OPTIONS
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--remote-debugging-port=9222")
    
    # 2. USER AGENT (Cloudflare Bypassing)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 3. RENDER SPECIFIC
    if IS_RENDER:
        chrome_options.add_argument("--headless=new")
        chrome_options.binary_location = "/usr/bin/chromium"
    else:
        chrome_options.add_argument("--headless=new")

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

    if IS_RENDER:
        print(f"   Binary: /usr/bin/chromium")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


def get_meeting_links(driver):
    # 1. Construct Dynamic URL (2022-01-01 to Today)
    start_date = "2022-01-01"
    end_date = datetime.date.today().strftime("%Y-%m-%d")

    # ud=3610 is Økonomiudvalget
    search_url = f"{BASE_URL}/da?from_date={start_date}&to_date={end_date}&ud=3610"

    print(f"--- Step 1: Visiting Search URL ---")
    print(f"    {search_url}")

    driver.get(search_url)

    # Wait for results to load
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "entity-teaser--os2web-meetings-meeting"))
        )
    except:
        print("    ! Timeout or no meetings found.")
        return []

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    meetings = []

    # Find all meeting blocks
    teasers = soup.find_all("a", class_="entity-teaser--os2web-meetings-meeting")

    for teaser in teasers:
        href = teaser.get('href')
        if not href: continue

        full_url = urljoin(BASE_URL, href)

        # 1. Check Type (Referat vs Dagsorden)
        # Look for the h3 inside the type field
        type_div = teaser.find("div", class_="field--name-field-os2web-m-type")
        if type_div:
            type_text = type_div.get_text(strip=True).lower()
            if "referat" not in type_text:
                continue  # Skip agendas

        # 2. Extract Date
        # Format in HTML: "25. november 2025 - 15:30"
        date_div = teaser.find("div", class_="meeting-teaser-time")
        date_text = date_div.get_text(strip=True) if date_div else "0000"
        
        date_obj = None
        try:
            # Regex for "25. november 2025"
            date_match = re.search(r"(\d+)\.\s+([a-z]+)\s+(\d{4})", date_text.lower())
            if date_match:
                day, month_name, year = date_match.groups()
                months = {
                    'januar': '01', 'februar': '02', 'marts': '03', 'april': '04',
                    'maj': '05', 'juni': '06', 'juli': '07', 'august': '08',
                    'september': '09', 'oktober': '10', 'november': '11', 'december': '12'
                }
                m = months.get(month_name, '01')
                filename = f"{year}-{m}-{day.zfill(2)}_middelfart_oekonomiudvalget.pdf"
                date_obj = datetime.date(int(year), int(m), int(day))
            else:
                filename = f"middelfart_unknown_{len(meetings)}.pdf"
        except:
            filename = f"middelfart_unknown_{len(meetings)}.pdf"

        # Deduplicate
        if not any(m['url'] == full_url for m in meetings):
            meetings.append({
                "url": full_url,
                "filename": filename,
                "date_obj": date_obj
            })

    print(f"  > Found {len(meetings)} 'Referat' meetings.")
    return meetings


def save_page_as_pdf(driver, meeting):
    filename = meeting['filename']
    url = meeting['url']
    date_obj = meeting['date_obj']

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
        # print(f"Skipping {filename} (Exists locally)")
        return True

    print(f"Processing: {filename}")

    try:
        driver.get(url)
        time.sleep(3)  # Wait for content

        # --- CLEANUP HTML (Remove Headers/Footers) ---
        driver.execute_script("""
            // 1. Remove Cookie Banners
            var badIds = ['sliding-popup', 'eu-cookie-withdraw-wrapper', 'cookie-consent-banner'];
            badIds.forEach(id => { var el = document.getElementById(id); if(el) el.remove(); });

            // 2. Open all Details/Accordions (if any exist)
            var details = document.querySelectorAll('details');
            details.forEach(d => d.setAttribute('open', 'true'));

            // 3. Hide Site Navigation & Footer
            var classesToHide = [
                'custom-header',      // Top Logo/Menu
                'section--breadcrumb-bar', // Breadcrumbs & Print Button row
                'footer',             // Bottom footer
                'action-buttons',     // Floating buttons
                'back-to-top'
            ];

            classesToHide.forEach(cls => {
                var els = document.getElementsByClassName(cls);
                for(var i=0; i<els.length; i++) els[i].style.display = 'none';
            });

            // 4. Force Content Width
            var main = document.querySelector('.region-content');
            if(main) {
                main.style.width = '100%';
                main.style.margin = '0';
                main.style.padding = '0';
            }
        """)

        time.sleep(1)

        # --- GENERATE PDF ---
        result = driver.execute_cdp_cmd("Page.printToPDF", {
            "landscape": False,
            "displayHeaderFooter": False,
            "printBackground": True,
            "preferCSSPageSize": True,
            "marginTop": 0.4,  # Inches
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4
        })

        with open(local_path, 'wb') as f:
            f.write(base64.b64decode(result['data']))

        # --- UPLOAD IF ON RENDER ---
        if IS_RENDER:
            scraper_utils.upload_to_wasabi(local_path, WASABI_BUCKET, filename)
            if os.path.exists(local_path):
                os.remove(local_path)
        else:
            print("  > Saved.")
            
        return True

    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False


def run_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()
    if not driver: return

    try:
        meetings = get_meeting_links(driver)

        download_limit = scraper_utils.get_download_limit()
        processed_count = 0
        
        for i, meeting in enumerate(meetings):
            if download_limit and processed_count >= download_limit:
                print(f"Reached download limit ({download_limit}). Stopping.")
                break
                
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            if save_page_as_pdf(driver, meeting):
                processed_count += 1
                
    finally:
        driver.quit()
        print("\n--- Done! ---")


if __name__ == "__main__":
    run_scraper()