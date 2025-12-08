import os
import time
import re
import html as html_parser  # To decode &amp; to &
import requests
from urllib.parse import unquote

# Import Selenium
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
DOWNLOAD_DIR = os.path.abspath('raw_files_aalborg')
START_URL = "https://referater.aalborg.dk/politiske-udvalg/oekonomiudvalget"
BASE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


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
        # Pattern matches: window.open('https://apps.aalborgkommune.dk/aakReferater/Pdf.aspx?pdfnavn=...')
        # We look for the URL inside the single quotes of window.open()
        match = re.search(r"window\.open\('([^']+)'\)", page_html)

        if not match:
            # Fallback: look for the URL pattern directly if window.open isn't used exactly that way
            match = re.search(r"(https://apps\.aalborgkommune\.dk/aakReferater/Pdf\.aspx[^']*)", page_html)

        if not match:
            print(f"Skipping: No PDF link found on {meeting_url}")
            return

        raw_link = match.group(1)

        # 3. Decode HTML entities (Change &amp; back to &)
        pdf_url = html_parser.unescape(raw_link)

        # 4. Generate Filename
        # The URL looks like: .../Pdf.aspx?pdfnavn=2024-04-08 10.30.pdf&type=moede...
        filename = "aalborg_unknown.pdf"
        name_match = re.search(r'pdfnavn=([^&]*)', pdf_url)

        if name_match:
            original_name = unquote(name_match.group(1))  # Decode %20 to space
            # Try to extract date YYYY-MM-DD
            date_part = re.search(r'(\d{4}-\d{2}-\d{2})', original_name)
            if date_part:
                filename = f"{date_part.group(1)}_aalborg_oekonomiudvalget.pdf"
            else:
                filename = f"aalborg_oekonomiudvalget_{original_name}"

        # Clean filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        final_path = os.path.join(DOWNLOAD_DIR, filename)

        if os.path.exists(final_path):
            # print(f"Skipping (Exists): {filename}")
            return

        # 5. Download
        print(f"Downloading: {filename}")
        pdf_resp = session.get(pdf_url, stream=True)
        pdf_resp.raise_for_status()

        with open(final_path, 'wb') as f:
            for chunk in pdf_resp.iter_content(chunk_size=8192):
                f.write(chunk)

    except Exception as e:
        print(f"Error downloading from {meeting_url}: {e}")


def run_aalborg_scrape():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()

    # 1. Get Links
    links = get_aalborg_meeting_links(driver)
    driver.quit()

    if not links:
        print("No links found.")
        return

    # 2. Download Files
    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    print(f"\n--- Step 2: Downloading {len(links)} PDFs ---")
    for i, link in enumerate(links):
        # Progress
        print(f"[{i + 1}/{len(links)}]", end=" ")
        download_pdf(session, link)

    print("\n--- Aalborg Scrape Complete! ---")


if __name__ == "__main__":
    run_aalborg_scrape()