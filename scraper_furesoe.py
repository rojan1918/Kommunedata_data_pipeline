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
DOWNLOAD_DIR = os.path.abspath('raw_files_furesoe')
START_URL = "https://furesoe.meetingsplus.dk/committees/okonomiudvalget"
BASE_URL = "https://furesoe.meetingsplus.dk"


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Keep visible for safety
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    # Force download to our folder
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


# --- STEP 1: FIND MEETING LINKS AND DATES ---
def get_meeting_info(driver):
    print(f"--- Step 1: Scraping Meeting List from {START_URL} ---")
    driver.get(START_URL)

    # Wait for the Recent Content container
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "committeesRecentContent"))
        )
    except TimeoutException:
        print("Error: Could not load meeting list.")
        return []

    # Find all rows in the recent content
    # We look for the specific class you identified: 'accessible-table-cell'
    # inside the recent content div
    links = driver.find_elements(By.CSS_SELECTOR, "#committeesRecentContent a.accessible-table-cell")

    meetings = []  # List of tuples: (url, date_string)
    seen_urls = set()

    for link in links:
        href = link.get_attribute('href')
        text = link.text

        # Skip duplicates or invalid links
        if not href or href in seen_urls:
            continue

        # Extract Date from text (e.g., "2025-11-04")
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)

        if date_match:
            date_str = date_match.group(1)
            meetings.append((href, date_str))
            seen_urls.add(href)
        else:
            # Fallback: Try to get date from aria-label
            aria = link.get_attribute("aria-label")
            date_match_aria = re.search(r"(\d{4}-\d{2}-\d{2})", aria if aria else "")
            if date_match_aria:
                date_str = date_match_aria.group(1)
                meetings.append((href, date_str))
                seen_urls.add(href)

    print(f"  > Found {len(meetings)} unique meetings with dates.")
    return meetings


# --- STEP 2: DOWNLOAD PDF ---
def download_meeting_pdf(driver, meeting_url, date_str):
    # 1. Generate Filename
    filename = f"{date_str}_furesoe_oekonomiudvalget.pdf"
    final_path = os.path.join(DOWNLOAD_DIR, filename)

    if os.path.exists(final_path):
        # print(f"Skipping (Exists): {filename}")
        return

    # 2. Visit Meeting Page
    driver.get(meeting_url)

    try:
        # 3. Find 'Vis referat' button by ID 'openProtocol'
        wait = WebDriverWait(driver, 5)
        button = wait.until(EC.presence_of_element_located((By.ID, "openProtocol")))

        pdf_url = button.get_attribute('href')

        # OPTIONAL: Change 'downloadMode=open' to 'downloadMode=download' to be safe
        if "downloadMode=open" in pdf_url:
            pdf_url = pdf_url.replace("downloadMode=open", "downloadMode=download")

        print(f"Downloading: {filename} ...")

        # 4. Snapshot files before download
        files_before = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))

        # 5. Trigger Download
        driver.get(pdf_url)

        # 6. Wait for file
        timeout = time.time() + 30
        while time.time() < timeout:
            files_now = set(glob(os.path.join(DOWNLOAD_DIR, "*.pdf")))
            new_files = files_now - files_before

            if new_files:
                new_file = new_files.pop()
                # Wait if it's still a temp file
                if not new_file.endswith(".crdownload"):
                    # Rename
                    time.sleep(1)  # Release lock
                    os.rename(new_file, final_path)
                    print("  > Success!")
                    return
            time.sleep(0.5)

        print("  > Error: Timeout waiting for file.")

    except TimeoutException:
        print(f"  > Skipped: No 'Vis referat' (openProtocol) button found on {meeting_url}")
    except Exception as e:
        print(f"  > Error: {e}")


# --- MAIN ---
def run_furesoe_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()

    # 1. Get list of meetings + dates
    meetings_data = get_meeting_info(driver)

    # 2. Process downloads
    print(f"\n--- Step 2: Downloading {len(meetings_data)} PDFs ---")
    for i, (url, date) in enumerate(meetings_data):
        print(f"[{i + 1}/{len(meetings_data)}]", end=" ")
        download_meeting_pdf(driver, url, date)

    driver.quit()
    print("\n--- Furesoe Scrape Complete! ---")


if __name__ == "__main__":
    run_furesoe_scraper()