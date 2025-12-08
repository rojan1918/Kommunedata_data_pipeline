import os
import time
import csv
from urllib.parse import urljoin

# Import Selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
except ImportError:
    print("Error: Selenium library not found. Run: pip install selenium")
    exit()

# --- CONFIGURATION ---
INPUT_FILE = "all_municipality_urls.txt"
OUTPUT_FILE = "found_start_urls.csv"


def read_urls_from_file(filepath):
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        urls = []
        for line in f:
            clean_line = line.strip()
            if clean_line and clean_line.startswith('http'):
                urls.append(clean_line)
    return urls


def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not os.path.exists(driver_path):
        driver_path = 'chromedriver'

    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def find_committee_url_interactive(driver, base_url):
    print(f"Scanning: {base_url} ... ", end="", flush=True)

    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 15)  # Increased timeout to 15s

        # --- THE FIX: WAIT FOR TEXT TO APPEAR ---
        # Instead of just waiting for 'body', we wait for the word "Økonomi"
        # to appear ANYWHERE in the DOM (even if hidden).
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Økonomi')]")
            ))
        except TimeoutException:
            # If "Økonomi" doesn't appear after 15s, the page might use a different term
            # or is very slow. We proceed anyway to try other strategies.
            pass

        # Optional: Scroll to bottom to trigger any lazy loading
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        # Keywords to look for
        keywords = ["Økonomiudvalg", "Økonomiudvalget", "Økonomi", "ØU"]

        # --- STRATEGY 1: The "Data-Value" Extraction (Deep Search) ---
        for keyword in keywords:
            try:
                # Find ALL elements containing the text, regardless of visibility
                xpath = f"//*[contains(text(), '{keyword}')]"
                elements = driver.find_elements(By.XPATH, xpath)

                for el in elements:
                    # Check parent hierarchy (sometimes the data-value is on the <a>, but text is in a span)
                    # We check the element itself and its immediate parent

                    # 1. Check element itself
                    val = el.get_attribute("data-value")
                    if val:
                        final_url = f"{base_url.rstrip('/')}/?request.kriterie.udvalgId={val}"
                        print("FOUND (via data-value)!")
                        return final_url

                    # 2. Check Parent (common in these nested dropdowns)
                    try:
                        parent = el.find_element(By.XPATH, "..")
                        val_p = parent.get_attribute("data-value")
                        if val_p:
                            final_url = f"{base_url.rstrip('/')}/?request.kriterie.udvalgId={val_p}"
                            print("FOUND (via parent data-value)!")
                            return final_url
                    except:
                        pass

                    # 3. Check for direct href
                    href = el.get_attribute("href")
                    if href and ("udvalgId" in href or "committeeId" in href):
                        print("FOUND (via href)!")
                        return urljoin(base_url, href)

            except Exception:
                continue

        # --- STRATEGY 2: Direct Link Check (Fallback) ---
        for keyword in keywords:
            try:
                xpath = f"//a[contains(., '{keyword}')]"
                elements = driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    href = el.get_attribute('href')
                    if href and ("/udvalg/" in href or "id=" in href):
                        print("FOUND (Direct Link)!")
                        return urljoin(base_url, href)
            except:
                continue

        print("Not Found.")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


# --- MAIN ORCHESTRATOR ---
def run_discovery():
    base_urls = read_urls_from_file(INPUT_FILE)
    if not base_urls:
        print("No URLs found. Exiting.")
        return

    driver = get_driver()

    with open(OUTPUT_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Base URL', 'Start URL'])

        print(f"--- Starting Discovery on {len(base_urls)} Municipalities ---")

        for i, base_url in enumerate(base_urls):
            if not base_url or base_url.startswith("#"): continue

            specific_url = find_committee_url_interactive(driver, base_url)

            if specific_url:
                writer.writerow([base_url, specific_url])
                f.flush()

            time.sleep(0.5)

    driver.quit()
    print("\n--- Discovery Complete! ---")
    print(f"Results saved to '{OUTPUT_FILE}'")


if __name__ == "__main__":
    run_discovery()