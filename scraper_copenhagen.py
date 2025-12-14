import os
import re
import datetime
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from weasyprint import HTML

# --- UTILS ---
import scraper_utils

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_DOMAIN = "https://www.kk.dk"
BASE_PATH = "/dagsordener-og-referater/%C3%98konomiudvalget"
WASABI_BUCKET = "raw-files-copenhagen"

if IS_RENDER:
    OUTPUT_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    OUTPUT_DIR = os.path.abspath("referater_kobenhavn")
    print(f"--- RUNNING LOCALLY ---")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_all_meeting_urls():
    start_date = "2022-01-01"
    end_date = datetime.date.today().strftime("%Y-%m-%d")

    current_url = (
        f"{BASE_DOMAIN}{BASE_PATH}"
        f"?agenda_meeting_date_value%5Bmin%5D={start_date}"
        f"&agenda_meeting_date_value%5Bmax%5D={end_date}"
    )

    all_meetings = []
    page_num = 1

    print(f"--- Step 1: Finding meetings from {start_date} to {end_date} ---")

    while current_url:
        print(f"  > Scanning Page {page_num}...")
        try:
            response = requests.get(current_url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            rows = soup.find_all("tr")
            found_on_page = 0

            for row in rows:
                # The meeting link is inside the 3rd column (views-field-nothing)
                link_container = row.find("td", class_="views-field-nothing")
                if link_container:
                    # FIX: Look for the specific link inside the list item, NOT the committee link
                    # We search for any <a> that contains "Referat" or "Dagsorden" in the text
                    target_link = link_container.find("a", string=re.compile(r"Referat|Dagsorden", re.I))

                    if target_link and target_link.get('href'):
                        href = target_link.get('href')

                        # Extract Date
                        date_col = row.find("td", class_="views-field-agenda-meeting-date")
                        date_text = date_col.get_text(strip=True) if date_col else "00-00-0000"
                        
                        file_date = "0000-00-00"
                        date_obj = None

                        try:
                            d_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_text)
                            if d_match:
                                d, m, y = d_match.groups()
                                file_date = f"{y}-{m}-{d}"
                                date_obj = datetime.date(int(y), int(m), int(d))
                        except:
                            pass

                        full_url = urljoin(BASE_DOMAIN, href)

                        # Only process Referats
                        if "referat" in href.lower():
                            all_meetings.append({
                                "url": full_url,
                                "filename": f"{file_date}_kk_oekonomiudvalget.pdf",
                                "date": file_date,
                                "date_obj": date_obj
                            })
                            found_on_page += 1

            print(f"    Found {found_on_page} meetings.")

            # Pagination
            next_li = soup.find("li", class_="pager__item--next")
            if next_li and next_li.find("a"):
                next_href = next_li.find("a").get("href")
                current_url = f"{BASE_DOMAIN}{BASE_PATH}{next_href}"
                page_num += 1
            else:
                current_url = None

        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            break

    return all_meetings


def get_agenda_items(meeting_url):
    """
    Visits a meeting page and gets the links for every agenda point.
    Robust strategy: Finds ANY row that contains a 'item-number' cell.
    """
    try:
        response = requests.get(meeting_url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []

        # Find ALL table rows on the page
        rows = soup.find_all("tr")

        for row in rows:
            # --- FINGERPRINT CHECK ---
            # We only want rows that have a <td class="item-number">
            # This automatically filters out headers (<th>) and other tables.
            num_col = row.find("td", class_="item-number")

            if not num_col:
                continue  # Skip this row (it's a header or irrelevant)

            # 1. Get Point Number
            # Clean up text: "Punkt 1" -> "1"
            number = num_col.get_text(strip=True).replace("Punkt", "").strip()

            # 2. Get Link & Title
            content_col = row.find("td", class_="item-content")
            if content_col:
                link = content_col.find("a")
                if link and link.get('href'):
                    title = link.get_text(strip=True)
                    href = link.get('href')
                    full_url = urljoin(BASE_DOMAIN, href)

                    items.append({
                        "number": number,
                        "title": title,
                        "url": full_url
                    })

        return items

    except Exception as e:
        print(f"    ! Error getting items: {e}")
        return []


def scrape_item_content(item_url):
    try:
        response = requests.get(item_url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')

        content_div = soup.find("div", class_="node__content")
        if not content_div:
            return "<p><em>Ingen indhold.</em></p>"

        # Cleanup unwanted elements
        for btn in content_div.find_all("a", class_="btn-appendices"): btn.decompose()
        for appendix in content_div.find_all("div", id="agenda-element-appendices"): appendix.decompose()
        for appendix in content_div.find_all("div", class_="agenda-element-appendix"): appendix.decompose()

        return str(content_div)
    except:
        return ""


def create_meeting_pdf(meeting, agenda_items):
    filename = meeting['filename']
    output_path = os.path.join(OUTPUT_DIR, filename)
    
    # --- CHECK IF EXISTS (Cloud or Local) ---
    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                s3.head_object(Bucket=WASABI_BUCKET, Key=filename)
                print(f"Skipping {filename} (Already in Wasabi)")
                return True # Count as processed
            except:
                pass
    elif os.path.exists(output_path):
        # print(f"Skipping {filename} (Exists locally)")
        return True

    full_html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4; margin: 2cm; }}
            body {{ font-family: sans-serif; font-size: 12px; line-height: 1.5; }}
            h1 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 10px; }}
            h2 {{ background-color: #eee; padding: 8px; border-left: 5px solid #003366; margin-top: 20px; page-break-after: avoid; }}
            .meta {{ color: #666; margin-bottom: 30px; }}
            .agenda-item {{ page-break-inside: avoid; margin-bottom: 30px; }}
            img {{ max-width: 100%; height: auto; }}
        </style>
    </head>
    <body>
        <h1>Referat: Økonomiudvalget</h1>
        <div class="meta">
            <strong>Dato:</strong> {meeting['date']}<br>
            <strong>Original Link:</strong> <a href="{meeting['url']}">{meeting['url']}</a>
        </div>
    """

    print(f"    > Scraping {len(agenda_items)} items for {filename}...")

    for item in agenda_items:
        html_content = scrape_item_content(item['url'])
        full_html += f"""
        <div class="agenda-item">
            <h2>Punkt {item['number']}: {item['title']}</h2>
            <div>{html_content}</div>
        </div>
        """

    full_html += "</body></html>"

    try:
        HTML(string=full_html).write_pdf(output_path)
        
        # --- UPLOAD IF ON RENDER ---
        if IS_RENDER:
            scraper_utils.upload_to_wasabi(output_path, WASABI_BUCKET, filename)
            if os.path.exists(output_path):
                os.remove(output_path)
        else:
            print(f"    > Saved: {filename}")
            
        return True
    except Exception as e:
        print(f"    ! Error generating PDF: {e}")
        return False


def run_scraper():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Get ALL meetings
    meetings = get_all_meeting_urls()
    
    # 2. Process
    download_limit = scraper_utils.get_download_limit()
    processed_count = 0

    for i, meeting in enumerate(meetings):
        if download_limit and processed_count >= download_limit:
            print(f"Reached download limit ({download_limit}). Stopping.")
            break
            
        date_obj = meeting.get('date_obj')
        # --- DATE FILTERING ---
        if date_obj and not scraper_utils.should_scrape(date_obj):
             # print(f"Skipping {meeting['filename']} (Filtered by Date)")
             continue

        print(f"[{i + 1}/{len(meetings)}] Processing {meeting['date']}...")

        agenda_items = get_agenda_items(meeting['url'])
        if agenda_items:
            if create_meeting_pdf(meeting, agenda_items):
                processed_count += 1
        else:
            print("    > No agenda items found.")

    print("--- Copenhagen Scrape Complete ---")


if __name__ == "__main__":
    run_scraper()