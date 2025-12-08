import os
import time
import re
import requests
from urllib.parse import urljoin

# Import Selenium
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
DOWNLOAD_DIR = os.path.abspath('raw_files_syddjurs')
BASE_URL = "https://aabendagsorden.syddjurs.dk"
START_URL = "https://aabendagsorden.syddjurs.dk/"
# Date to search from (DD/MM/YYYY)
START_DATE = "01/01/2023"


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not os.path.exists(driver_path):
        driver_path = 'chromedriver'

    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


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

                    link_el = row.find_element(By.CSS_SELECTOR, "a.row-link")
                    href = link_el.get_attribute('href')

                    if href and href not in seen_urls:
                        all_meetings.append((href, iso_date))
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
def download_pdf(driver, meeting_url, date_str):
    filename = f"{date_str}_syddjurs_oekonomiudvalget.pdf"
    final_path = os.path.join(DOWNLOAD_DIR, filename)

    if os.path.exists(final_path):
        return

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

            with open(final_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("   > Success!")
        else:
            print(f"   > Skipped: Button found but attributes missing.")

    except TimeoutException:
        print(f"   > Skipped: Download button not loaded/found on page.")
    except Exception as e:
        print(f"   > Error: {e}")


# --- MAIN ---
def run_syddjurs_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()

    if not perform_search(driver):
        driver.quit()
        return

    meetings = get_meeting_links(driver)

    if not meetings:
        print("No meetings found.")
        driver.quit()
        return

    print(f"\n--- Step 3: Downloading {len(meetings)} PDFs ---")
    for i, (url, date) in enumerate(meetings):
        download_pdf(driver, url, date)

    driver.quit()
    print("\n--- Syddjurs Scrape Complete! ---")


if __name__ == "__main__":
    run_syddjurs_scraper()