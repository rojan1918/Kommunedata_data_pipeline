import os
import time
import re
from glob import glob

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
DOWNLOAD_DIR = os.path.abspath('raw_files_hedensted')
# Use the specific deep link you found
START_URL = "https://www.hedensted.dk/politik-og-indflydelse/kommunalbestyrelse-og-udvalg/dagsordener-og-referater/oekonomiudvalget-dagsordener-og-referater#agenda7560"
BASE_URL = "https://www.hedensted.dk"


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not os.path.exists(driver_path):
        driver_path = 'chromedriver'

    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# --- STEP 1: FIND MEETING LINKS ---
def get_meeting_links(driver):
    print(f"--- Step 1: Scraping Meeting List ---")
    driver.get(START_URL)
    time.sleep(2)  # Wait for initial load

    # 1. FORCE OPEN THE ACCORDION
    # Even with the link #agenda7560, we should manually ensure it's open
    # to trigger any lazy-loaded content.
    try:
        print("   > Locating accordion 'agenda7560'...")
        wait = WebDriverWait(driver, 10)

        # Find the specific accordion container
        accordion_container = wait.until(EC.presence_of_element_located((By.ID, "agenda7560")))

        # Find the header button inside it
        header_btn = accordion_container.find_element(By.CLASS_NAME, "js-accordion-header")

        # Check if it's already expanded (aria-expanded="true")
        is_expanded = header_btn.get_attribute("aria-expanded")

        if is_expanded != "true":
            print("   > Accordion is closed. Clicking to open...")
            # Use JS click to be safe against overlays
            driver.execute_script("arguments[0].click();", header_btn)
            time.sleep(2)  # Wait for list to render
        else:
            print("   > Accordion is already open.")

    except Exception as e:
        print(f"   > Warning: Issue interacting with accordion: {e}")

    # 2. SCRAPE THE LINKS
    try:
        # Now look for links specifically INSIDE that accordion
        # Selector: #agenda7560 .list__links a.list__link
        links_selector = "#agenda7560 .list__links a.list__link"

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, links_selector)))
        link_elements = driver.find_elements(By.CSS_SELECTOR, links_selector)
    except TimeoutException:
        print("Error: No links found inside #agenda7560.")
        return []

    print(f"  > Found {len(link_elements)} potential links.")

    meetings = []

    for el in link_elements:
        href = el.get_attribute('href')
        if not href: continue

        # Extract date from URL
        # Pattern: .../dagsorden/Oekonomiudvalget_2022/10-11-2025...
        match = re.search(r"/(\d{2}-\d{2}-\d{4})", href)

        if match:
            date_raw = match.group(1)
            d, m, y = date_raw.split('-')
            date_str = f"{y}-{m}-{d}"
            meetings.append((href, date_str))

    print(f"  > Found {len(meetings)} valid meeting links.")
    return meetings


# --- STEP 2: DOWNLOAD PDF ---
def download_pdf(driver, meeting_url, date_str):
    filename = f"{date_str}_hedensted_oekonomiudvalget.pdf"
    final_path = os.path.join(DOWNLOAD_DIR, filename)

    if os.path.exists(final_path):
        return

    driver.get(meeting_url)

    try:
        wait = WebDriverWait(driver, 5)
        button = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn__link.attachment-link")))

        pdf_href = button.get_attribute('href')
        if not pdf_href: return

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
                    os.rename(new_file, final_path)
                    print("  > Success!")
                    return
            time.sleep(0.5)

        print("  > Error: Timeout waiting for file.")

    except TimeoutException:
        print(f"  > Skipped: No PDF found on {meeting_url}")
    except Exception as e:
        print(f"  > Error: {e}")


# --- MAIN ---
def run_hedensted_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()

    links = get_meeting_links(driver)

    print(f"\n--- Step 2: Downloading {len(links)} PDFs ---")
    for i, (url, date) in enumerate(links):
        print(f"[{i + 1}/{len(links)}]", end=" ")
        download_pdf(driver, url, date)

    driver.quit()
    print("\n--- Hedensted Scrape Complete! ---")


if __name__ == "__main__":
    run_hedensted_scraper()