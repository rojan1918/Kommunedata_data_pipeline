import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
START_URL = "https://billund.meetingsplus.dk/committees/okonomiudvalget"


def get_driver():
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Keep visible so you can watch
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not os.path.exists(driver_path):
        driver_path = 'chromedriver'

    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def investigate_billund():
    driver = get_driver()
    print(f"--- Investigating Billund ({START_URL}) ---")

    try:
        driver.get(START_URL)
        wait = WebDriverWait(driver, 15)

        # 1. Cookie Banner (Common on these sites)
        try:
            print("Checking for cookies...")
            cookie_btn = wait.until(EC.element_to_be_clickable((By.ID, "cookie-accept-all")))  # Common ID
            cookie_btn.click()
            time.sleep(1)
        except:
            print("No cookie banner found or skipped.")

        # 2. Find the 'Recent Content' tab
        print("\n--- 1. Looking for Meeting List ---")
        # We look for the container mentioned in your URL
        container = wait.until(EC.presence_of_element_located((By.ID, "committeesRecentContent")))

        # Find links inside this container
        links = container.find_elements(By.TAG_NAME, "a")

        print(f"Found {len(links)} links in the recent section.")

        meeting_url = None

        # Print the first few meaningful links
        count = 0
        for link in links:
            text = link.text.strip()
            href = link.get_attribute('href')

            # Filter out empty links or small icons
            if href and len(text) > 5:
                print(f"Link {count + 1}: Text='{text}' | HREF='{href}'")
                if meeting_url is None:
                    meeting_url = href  # Save the first one to visit
                count += 1
                if count >= 3: break

        if not meeting_url:
            print("CRITICAL: Could not find any meeting links.")
            return

        # 3. Visit the first meeting
        print(f"\n--- 2. Visiting First Meeting: {meeting_url} ---")
        driver.get(meeting_url)
        time.sleep(3)

        # 4. Hunt for PDF Buttons
        print("Scanning for PDF download buttons...")

        # Strategy A: Look for "Referat" or "PDF" text
        buttons = driver.find_elements(By.XPATH,
                                       "//*[contains(text(), 'Referat') or contains(text(), 'Hent') or contains(text(), 'PDF')]")

        if buttons:
            print(f"Found {len(buttons)} potential download elements:")
            for btn in buttons:
                # Ignore huge blocks of text
                if len(btn.text) < 50:
                    print(f"  > Tag: {btn.tag_name} | Text: '{btn.text}' | HREF: {btn.get_attribute('href')}")
                    print(f"    OuterHTML: {btn.get_attribute('outerHTML')[:200]}...")
        else:
            print("No text-based buttons found. Checking for specific icons/classes...")
            # Strategy B: Look for common icon classes
            icons = driver.find_elements(By.CSS_SELECTOR, ".fa-file-pdf, .icon-pdf")
            for icon in icons:
                # Get parent
                parent = icon.find_element(By.XPATH, "..")
                print(f"  > Found Icon Parent: {parent.tag_name} | HREF: {parent.get_attribute('href')}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("\nClosing browser...")
        driver.quit()


if __name__ == "__main__":
    investigate_billund()