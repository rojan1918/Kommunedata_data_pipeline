# local_scraper.py
import os
import re
import time
import base64
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.print_page_options import PrintOptions

# --- CONFIGURATION ---
DOWNLOAD_DIR = os.path.abspath('referater_ishoj_local')
START_URL = 'https://ishoj.dk/borger/demokrati/dagsordener-og-referater/'


def get_driver():
    print("Initializing Local Browser...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    # We run visible (NOT headless) to ensure we pass Cloudflare
    driver = uc.Chrome(options=options, version_main=141)
    return driver


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


def save_page_as_pdf(driver, url):
    try:
        # Extract date for filename (e.g., 18-08-2025)
        date_match = re.search(r'(\d{2}-\d{2}-\d{4})', url)
        if date_match:
            d, m, y = date_match.group(1).split('-')
            filename = f"{y}-{m}-{d}_ishoj_oekonomiudvalget.pdf"
        else:
            filename = f"ishoj_{url.split('/')[-1][:20]}.pdf"

        final_path = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(final_path):
            # print(f"Skipping {filename} (Exists)")
            return

        print(f"Processing: {filename}")
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
        result = driver.execute_cdp_cmd("Page.printToPDF", {
            "landscape": False,
            "displayHeaderFooter": False,
            "printBackground": True,
            "preferCSSPageSize": True,
        })

        with open(final_path, 'wb') as f:
            f.write(base64.b64decode(result['data']))

        print("  > Saved.")

    except Exception as e:
        print(f"Error saving PDF: {e}")


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    try:
        links = get_meeting_links(driver)

        if links:
            print(f"Starting download of {len(links)} files...")
            for i, link in enumerate(links):
                print(f"[{i + 1}/{len(links)}]", end=" ")
                save_page_as_pdf(driver, link)
        else:
            print("No links found. Check debug_failure.html.")

    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        driver.quit()
        print("\n--- Done ---")