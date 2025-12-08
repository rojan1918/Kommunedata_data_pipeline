import os
import time
import re
import requests
import subprocess
import platform
from glob import glob
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

# Import BeautifulSoup
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: BeautifulSoup library not found. Run: pip install beautifulsoup4")
    exit()

# --- CONFIGURATION ---
DOWNLOAD_DIR = os.path.abspath('raw_files_glostrup')
BASE_URL = "https://dagsorden.glostrup.dk"
START_URL = "https://dagsorden.glostrup.dk/"
START_DATE = "01/01/2023"


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    # chrome_options.add_argument("--disable-dev-shm-usage") # Linux optimization

    # Smart Driver Path Selection
    current_dir = os.getcwd()
    if platform.system() == "Windows":
        driver_path = os.path.join(current_dir, 'chromedriver.exe')
    else:
        # Linux/Render locations
        paths = ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver", os.path.join(current_dir, 'chromedriver')]
        driver_path = next((p for p in paths if os.path.exists(p)), None)

    if not driver_path or not os.path.exists(driver_path):
        # If local driver not found, try default PATH
        driver_path = 'chromedriver'

    try:
        service = Service(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- HELPER: SMART CONVERSION (WINDOWS/LINUX) ---
def convert_to_pdf(docx_path, output_dir):
    """
    Tries to convert DOCX to PDF using LibreOffice (soffice).
    Works on both Windows (if installed) and Linux.
    """
    print(f"   > Attempting conversion for {os.path.basename(docx_path)}...")

    # Determine the command for LibreOffice
    soffice_cmd = 'soffice'  # Default for Linux

    if platform.system() == "Windows":
        # Common Windows Install paths for LibreOffice
        possible_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
        ]
        found = False
        for p in possible_paths:
            if os.path.exists(p):
                soffice_cmd = p
                found = True
                break

        if not found:
            print("   > Warning: LibreOffice not found in standard Windows paths.")
            print("   > Skipping conversion. File saved as DOCX.")
            return False

    try:
        # Run the conversion command
        subprocess.run([
            soffice_cmd,
            '--headless',
            '--convert-to', 'pdf',
            docx_path,
            '--outdir', output_dir
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Verify Result
        base_name = os.path.splitext(os.path.basename(docx_path))[0]
        expected_pdf = os.path.join(output_dir, base_name + ".pdf")

        if os.path.exists(expected_pdf):
            print("   > Conversion successful. Deleting DOCX.")
            os.remove(docx_path)
            return True
        else:
            print("   > Error: LibreOffice ran but PDF was not created.")
            return False

    except FileNotFoundError:
        print(f"   > Error: The command '{soffice_cmd}' was not found.")
        if platform.system() == "Linux":
            print("   > On Render: Ensure LibreOffice is installed via Dockerfile.")
        return False
    except Exception as e:
        print(f"   > Error during conversion: {e}")
        return False


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

                    link_el = row.find_element(By.CSS_SELECTOR, "a.row-link")
                    href = link_el.get_attribute('href')

                    if href and href not in seen_urls:
                        all_meetings.append((href, iso_date))
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
def download_document(driver, meeting_url, date_str):
    filename_docx = f"{date_str}_glostrup_oekonomiudvalget.docx"
    filename_pdf = f"{date_str}_glostrup_oekonomiudvalget.pdf"

    final_path_docx = os.path.join(DOWNLOAD_DIR, filename_docx)
    final_path_pdf = os.path.join(DOWNLOAD_DIR, filename_pdf)

    if os.path.exists(final_path_pdf):
        return

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

            # Determine if we need to save as PDF directly or DOCX
            if 'pdf' in content_type or file_name.endswith('.pdf'):
                save_path = final_path_pdf
                needs_conversion = False
            else:
                save_path = final_path_docx
                needs_conversion = True

            print(f"   > Downloading...")
            with open(save_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Try conversion
            if needs_conversion:
                convert_to_pdf(final_path_docx, DOWNLOAD_DIR)

        else:
            print(f"   > Skipped: Button attributes missing.")

    except TimeoutException:
        print(f"   > Skipped: Download button not found.")
    except Exception as e:
        print(f"   > Error: {e}")


# --- MAIN ---
def run_glostrup_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    if not driver: return

    if not perform_search(driver):
        driver.quit()
        return

    meetings = get_meeting_links(driver)

    if not meetings:
        print("No meetings found.")
        driver.quit()
        return

    print(f"\n--- Step 3: Downloading {len(meetings)} Documents ---")
    for i, (url, date) in enumerate(meetings):
        print(f"[{i + 1}/{len(meetings)}]", end=" ")
        download_document(driver, url, date)

    driver.quit()
    print("\n--- Glostrup Scrape Complete! ---")


if __name__ == "__main__":
    run_glostrup_scraper()