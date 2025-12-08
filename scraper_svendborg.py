import os
import re
import time
import base64
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
DOWNLOAD_DIR = os.path.abspath('referater_svendborg')
# Base URL for the committee list
BASE_URL = "https://www.svendborg.dk/dagsordener-og-referater/?committees=8968"
DOMAIN = "https://www.svendborg.dk"


def get_driver():
    print("Initializing Browser...")
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    # Running visible (not headless) is usually safer for local testing
    options.add_argument("--headless=new")
    driver = uc.Chrome(options=options, version_main=141)
    return driver


def get_all_meeting_links(driver):
    print(f"--- Step 1: Finding meetings from {BASE_URL} ---")

    all_meetings = []
    offset = 0
    page_size = 12  # Svendborg loads 12 items per "Vis flere"

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

            # Check if we've seen these items before (end of loop detection)
            # Svendborg might redirect or show same items if offset is too high
            # For now, we rely on finding 0 items or checking specific content

            found_new = 0
            for item in items:
                # 1. Check Type (Dagsorden vs Referat)
                # The type is usually in the first span
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

                # 4. Create Filename
                # Format: 9. december 2025 -> 2025-12-09
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
                    else:
                        filename = f"svendborg_referat_{offset}.pdf"
                except:
                    filename = f"svendborg_referat_{offset}.pdf"

                # Deduplication check
                if not any(m['url'] == full_url for m in all_meetings):
                    all_meetings.append({
                        "url": full_url,
                        "filename": filename,
                        "date": date_text
                    })
                    found_new += 1

            print(f"    Found {found_new} referater on this page.")

            #if found_new == 0 and len(items) < page_size:
            if found_new == 0 and offset > 36:
                # If we found items but none were referats, AND list is short, we are likely at end
                print("    End of content reached.")
                break

            offset += page_size
            # Safety break for testing (remove if you want ALL history)
            # if offset > 100: break

        except Exception as e:
            print(f"    Error on offset {offset}: {e}")
            break

    return all_meetings


def save_page_as_pdf(driver, url, filename):
    final_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(final_path):
        # print(f"Skipping {filename} (Exists)")
        return

    print(f"Processing: {filename}")

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

            // Force main content to full width
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

        with open(final_path, 'wb') as f:
            f.write(base64.b64decode(result['data']))

        print("  > Saved.")

    except Exception as e:
        print(f"Error saving PDF: {e}")


def run_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    driver = get_driver()

    try:
        meetings = get_all_meeting_links(driver)
        print(f"Total meetings found: {len(meetings)}")

        for i, meeting in enumerate(meetings):
            print(f"[{i + 1}/{len(meetings)}]", end=" ")
            save_page_as_pdf(driver, meeting['url'], meeting['filename'])

    finally:
        driver.quit()
        print("\n--- Done! ---")


if __name__ == "__main__":
    run_scraper()