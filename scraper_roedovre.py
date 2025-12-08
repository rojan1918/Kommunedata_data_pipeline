import os
import time
import re
import base64
import json
import platform

# --- LIBRARIES ---
# Selenium for scraping
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

# Boto3 for Wasabi/S3
try:
    import boto3
    from botocore.exceptions import NoCredentialsError
except ImportError:
    print("Warning: boto3 not found. Cloud upload will fail if running on Render. (pip install boto3)")

# --- CONFIGURATION ---
# Detect if we are running on Render
IS_RENDER = os.environ.get('RENDER') == 'true'

BASE_URL = "https://www.rk.dk"
START_URL = "https://www.rk.dk/politik/politiske-udvalg/oekonomiudvalget"

# Wasabi Configuration (Only needed if on Render)
WASABI_ACCESS_KEY = os.environ.get("WASABI_ACCESS_KEY")
WASABI_SECRET_KEY = os.environ.get("WASABI_SECRET_KEY")
WASABI_BUCKET = "raw-files-roedovre"
WASABI_ENDPOINT = os.environ.get("WASABI_ENDPOINT", "https://s3.eu-central-1.wasabisys.com")

if IS_RENDER:
    # 1. RENDER CONFIGURATION
    # We use /tmp because we only need to hold the file for 2 seconds before uploading
    DOWNLOAD_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
    print(f"Temp storage: {DOWNLOAD_DIR}")
    print(f"Target Storage: Wasabi Bucket '{WASABI_BUCKET}'")
else:
    # 2. LOCAL CONFIGURATION
    DOWNLOAD_DIR = os.path.abspath('raw_files_roedovre')
    print(f"--- RUNNING LOCALLY ---")
    print(f"Saving files to Local Folder: {DOWNLOAD_DIR}")


# --- WASABI UPLOAD HELPER ---
def upload_to_wasabi(local_file_path, remote_filename):
    """
    Uploads a file to Wasabi and returns True if successful.
    """
    if not WASABI_ACCESS_KEY or not WASABI_SECRET_KEY:
        print("   > Error: Wasabi credentials missing.")
        return False

    s3 = boto3.client(
        's3',
        endpoint_url=WASABI_ENDPOINT,
        aws_access_key_id=WASABI_ACCESS_KEY,
        aws_secret_access_key=WASABI_SECRET_KEY
    )

    try:
        # Check if file already exists in Wasabi to save time
        try:
            s3.head_object(Bucket=WASABI_BUCKET, Key=remote_filename)
            print(f"   > Skipping: {remote_filename} already exists in Wasabi.")
            return "EXISTS"
        except:
            pass  # File does not exist, proceed

        print(f"   > Uploading to Wasabi...")
        with open(local_file_path, "rb") as f:
            s3.put_object(Bucket=WASABI_BUCKET, Key=remote_filename, Body=f)

        print(f"   > Upload Success!")
        return True

    except Exception as e:
        print(f"   > Wasabi Upload Error: {e}")
        return False


# --- SETUP SELENIUM ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument('--kiosk-printing')

    if IS_RENDER:
        chrome_options.add_argument("--headless=new")

    # Print settings
    settings = {
        "recentDestinations": [{"id": "Save as PDF", "origin": "local", "account": ""}],
        "selectedDestinationId": "Save as PDF",
        "version": 2
    }
    prefs = {
        'printing.print_preview_sticky_settings.appState': json.dumps(settings),
        'savefile.default_directory': DOWNLOAD_DIR
    }
    chrome_options.add_experimental_option('prefs', prefs)

    # Driver Path Logic
    driver_path = None
    if IS_RENDER:
        driver_path = "/usr/bin/chromedriver"
        if not os.path.exists(driver_path):
            driver_path = "/usr/local/bin/chromedriver"
    elif platform.system() == "Windows":
        driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
    else:
        driver_path = 'chromedriver'

    print(f"Starting Chrome with Driver: {driver_path}")

    try:
        service = Service(executable_path=driver_path) if driver_path and os.path.exists(
            str(driver_path)) else Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        print(f"Error starting Chrome: {e}")
        return None


# --- COOKIE BANNER HANDLER ---
def handle_cookies(driver):
    try:
        wait = WebDriverWait(driver, 3)
        xpath = "//button[contains(text(), 'Afvis alle') or contains(text(), 'Accepter alle') or contains(text(), 'Tillad alle')]"
        button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        if button:
            driver.execute_script("arguments[0].click();", button)
            time.sleep(1)
    except:
        pass


# --- PRINT TO PDF ---
def print_page_to_pdf(driver, output_path):
    try:
        pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "displayHeaderFooter": False
        })
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(pdf_data['data']))
        return True
    except Exception as e:
        print(f"   > Error printing PDF: {e}")
        return False


# --- STEP 1: GET LINKS ---
def get_meeting_links(driver):
    print(f"--- Getting Meeting List ---")
    driver.get(START_URL)
    handle_cookies(driver)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section.section-box .link a"))
        )
    except:
        return []

    links = driver.find_elements(By.CSS_SELECTOR, "section.section-box .link a")
    meetings = []

    for link in links:
        href = link.get_attribute('href')
        text = link.get_attribute("textContent")
        if text and href:
            match = re.search(r"(\d{2})-(\d{2})-(\d{4})", text.strip())
            if match:
                d, m, y = match.groups()
                meetings.append((href, f"{y}-{m}-{d}"))

    return meetings


# --- STEP 2: PROCESS MEETING ---
def process_meeting(driver, meeting_url, date_str):
    filename = f"{date_str}_roedovre_oekonomiudvalget.pdf"
    local_path = os.path.join(DOWNLOAD_DIR, filename)

    # 1. OPTIMIZATION: If on Render, check Wasabi BEFORE downloading
    # This saves computing power by not scraping files we already have
    if IS_RENDER:
        s3 = boto3.client('s3', endpoint_url=WASABI_ENDPOINT, aws_access_key_id=WASABI_ACCESS_KEY,
                          aws_secret_access_key=WASABI_SECRET_KEY)
        try:
            s3.head_object(Bucket=WASABI_BUCKET, Key=filename)
            print(f"Skipping {filename} (Already in Wasabi)")
            return
        except:
            pass  # File missing, continue to scrape

    # 2. Check local file existence (for local runs)
    elif os.path.exists(local_path):
        print(f"Skipping {filename} (Exists locally)")
        return

    print(f"Processing: {filename} ...")

    try:
        driver.get(meeting_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
        handle_cookies(driver)

        # 3. Save PDF locally (to disk or /tmp)
        if print_page_to_pdf(driver, local_path):

            # 4. IF RENDER: Upload to Wasabi then delete local file
            if IS_RENDER:
                upload_result = upload_to_wasabi(local_path, filename)
                # Cleanup: Remove the file from /tmp to save space
                if os.path.exists(local_path):
                    os.remove(local_path)
            else:
                print("   > Saved locally.")
        else:
            print("   > Failed to print.")

    except Exception as e:
        print(f"   > Error: {e}")


# --- MAIN ---
def run_roedovre_scraper():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    driver = get_driver()
    if not driver: return

    try:
        meetings = get_meeting_links(driver)
        print(f"Found {len(meetings)} meetings.")

        for i, (url, date) in enumerate(meetings):
            process_meeting(driver, url, date)

    finally:
        driver.quit()
        print("\n--- Complete! ---")


if __name__ == "__main__":
    run_roedovre_scraper()