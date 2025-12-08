import os
import time
import re
import base64
import json
import platform

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

# --- CONFIGURATION ---
# Detect if we are running on Render
IS_RENDER = os.environ.get('RENDER') == 'true'

BASE_URL = "https://www.rk.dk"
START_URL = "https://www.rk.dk/politik/politiske-udvalg/oekonomiudvalget"

if IS_RENDER:
    # 1. RENDER CONFIGURATION
    # Render persistent disks are usually mounted at /var/data (or whatever you named it)
    # We use an env var 'RENDER_DISK_PATH' or default to '/var/data'
    disk_path = os.environ.get('RENDER_DISK_PATH', '/var/data')
    DOWNLOAD_DIR = os.path.join(disk_path, 'referater_roedovre')
    print(f"--- RUNNING ON RENDER ---")
    print(f"Saving files to Persistent Disk: {DOWNLOAD_DIR}")
else:
    # 2. LOCAL CONFIGURATION (Windows/Mac)
    DOWNLOAD_DIR = os.path.abspath('raw_files_roedovre')
    print(f"--- RUNNING LOCALLY ---")
    print(f"Saving files to Local Folder: {DOWNLOAD_DIR}")


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()

    # --- SHARED OPTIONS ---
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument('--kiosk-printing')

    # --- ENVIRONMENT SPECIFIC OPTIONS ---
    if IS_RENDER:
        # Render MUST be headless
        chrome_options.add_argument("--headless=new")
    else:
        # Local: You might want to see the browser (comment out to run headless locally)
        # chrome_options.add_argument("--headless=new")
        pass

    # Print settings (Required for Page.printToPDF in some versions)
    settings = {
        "recentDestinations": [{
            "id": "Save as PDF",
            "origin": "local",
            "account": "",
        }],
        "selectedDestinationId": "Save as PDF",
        "version": 2
    }
    prefs = {
        'printing.print_preview_sticky_settings.appState': json.dumps(settings),
        'savefile.default_directory': DOWNLOAD_DIR
    }
    chrome_options.add_experimental_option('prefs', prefs)

    # --- DRIVER PATH FINDER ---
    driver_path = None

    if IS_RENDER:
        # On Render (Linux), chromedriver is usually in the path
        driver_path = "/usr/bin/chromedriver"
        if not os.path.exists(driver_path):
            driver_path = "/usr/local/bin/chromedriver"
    elif platform.system() == "Windows":
        # Local Windows
        driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    else:
        # Local Mac/Linux
        driver_path = 'chromedriver'

    # Fallback checks
    if driver_path and not os.path.exists(driver_path) and not IS_RENDER:
        # On local, if specific path fails, try simple command
        driver_path = 'chromedriver'

    print(f"Starting Chrome with Driver: {driver_path}")

    try:
        service = Service(executable_path=driver_path) if driver_path else Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- COOKIE BANNER HANDLER ---
def handle_cookies(driver):
    """
    Detects and clicks 'Accepter' or 'Afvis' on the cookie banner.
    """
    try:
        # Wait up to 3 seconds for a cookie banner
        wait = WebDriverWait(driver, 3)
        xpath = "//button[contains(text(), 'Afvis alle') or contains(text(), 'Accepter alle') or contains(text(), 'Tillad alle')]"
        button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))

        if button:
            print("   > Cookie banner found. Clicking...")
            driver.execute_script("arguments[0].click();", button)
            time.sleep(2)
            return True

    except TimeoutException:
        pass
    except Exception as e:
        print(f"   > Warning: Cookie handler issue: {e}")


# --- HELPER: PRINT TO PDF ---
def print_page_to_pdf(driver, output_path):
    try:
        # Use Selenium's DevTools command for printing
        pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "marginTop": 0.4,
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4,
            "displayHeaderFooter": False
        })

        with open(output_path, "wb") as f:
            f.write(base64.b64decode(pdf_data['data']))

        return True
    except Exception as e:
        print(f"   > Error printing PDF: {e}")
        return False


# --- STEP 1: GET LINKS ---
def get_meeting_links(driver):
    print(f"--- Step 1: Getting Meeting List from {START_URL} ---")
    driver.get(START_URL)

    handle_cookies(driver)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section.section-box .link a"))
        )
    except:
        print("Error: Could not find meeting list.")
        return []

    links = driver.find_elements(By.CSS_SELECTOR, "section.section-box .link a")
    meetings = []

    for link in links:
        href = link.get_attribute('href')
        text = link.get_attribute("textContent")

        if not text: continue
        text = text.strip().lower()
        if not href: continue

        match = re.search(r"(\d{2})-(\d{2})-(\d{4})", text)
        if match:
            d, m, y = match.groups()
            date_str = f"{y}-{m}-{d}"
            meetings.append((href, date_str))

    print(f"  > Found {len(meetings)} meetings.")
    return meetings


# --- STEP 2: VISIT AND PRINT ---
def process_meeting(driver, meeting_url, date_str):
    filename = f"{date_str}_roedovre_oekonomiudvalget.pdf"
    final_path = os.path.join(DOWNLOAD_DIR, filename)

    if os.path.exists(final_path):
        return

    print(f"Processing: {filename} ...")

    try:
        driver.get(meeting_url)

        # 1. Wait for content
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))

        # 2. Handle Cookies
        handle_cookies(driver)

        # 3. Print
        if print_page_to_pdf(driver, final_path):
            print("   > Success!")
        else:
            print("   > Failed to print.")

    except Exception as e:
        print(f"   > Error: {e}")


# --- MAIN ---
def run_roedovre_scraper():
    # Ensure directory exists (Recursive for cloud paths)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    if not driver: return

    try:
        meetings = get_meeting_links(driver)

        print(f"\n--- Step 2: Printing {len(meetings)} pages to PDF ---")
        for i, (url, date) in enumerate(meetings):
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            process_meeting(driver, url, date)

    finally:
        driver.quit()
        print("\n--- Rødovre Scrape Complete! ---")


if __name__ == "__main__":
    run_roedovre_scraper()