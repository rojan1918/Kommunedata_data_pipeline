import os
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# --- CONFIGURATION ---
DOWNLOAD_DIR = os.path.join(os.getcwd(), 'test_download_final')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# The wrapper link (that shows the button)
WRAPPER_URL = "https://dagsordener.esbjergkommune.dk/vis/pdf/dagsorden/4ddfe416-c1ea-46a5-96e7-cf14fc773fa5"
START_URL = "https://dagsordener.esbjergkommune.dk/"


def run_direct_download_test():
    print("--- Starting Direct Link Transformation Test ---")

    # 1. TRANSFORM THE URL
    # We extract the UUID and build the "GetDagsorden" link directly.
    # This bypasses the "Åbn" button page entirely.
    try:
        uuid = re.search(r"([a-f0-9\-]{36})", WRAPPER_URL).group(1)
        DIRECT_DOWNLOAD_URL = f"https://dagsordener.esbjergkommune.dk/pdf/GetDagsorden/{uuid}"
        print(f"1. Wrapper URL: {WRAPPER_URL}")
        print(f"2. Transformed: {DIRECT_DOWNLOAD_URL}")
    except Exception as e:
        print(f"Error extracting UUID: {e}")
        return

    # 2. Setup Chrome
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    # THIS IS CRITICAL:
    # We tell Chrome: "Never open PDF in viewer. Always download to disk."
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True  # <--- The magic setting
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    if not os.path.exists(driver_path):
        driver_path = 'chromedriver'

    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # 3. Init Session (Get Cookies)
        print("3. Visiting main page for cookies...")
        driver.get(START_URL)
        time.sleep(2)

        # 4. Go directly to the file
        print("4. Navigating to DIRECT download link...")
        driver.get(DIRECT_DOWNLOAD_URL)

        # 5. Wait for file
        print("5. Waiting for file...")
        start_time = time.time()
        while time.time() - start_time < 30:
            files = os.listdir(DOWNLOAD_DIR)
            pdf_files = [f for f in files if f.endswith('.pdf')]

            if pdf_files:
                print(f"\n!!! SUCCESS !!! Downloaded: {pdf_files[0]}")
                print(f"Location: {os.path.join(DOWNLOAD_DIR, pdf_files[0])}")
                return
            time.sleep(1)

        print("FAILURE: No file appeared.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing browser...")
        driver.quit()


if __name__ == "__main__":
    run_direct_download_test()