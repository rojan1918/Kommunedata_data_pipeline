import os
import re
import requests
import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pypdf import PdfWriter
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- UTILS ---
import scraper_utils

# --- CONFIGURATION ---
IS_RENDER = os.environ.get('RENDER') == 'true'
BASE_URL = "https://www.rksk.dk"
START_URL = "https://www.rksk.dk/om-kommunen/politiske-udvalg-2022-2025/oekonomiudvalget/dagsordener-referater"
WASABI_BUCKET = "raw-files-ringkoebing-skjern"

if IS_RENDER:
    OUTPUT_DIR = "/tmp"
    print(f"--- RUNNING ON RENDER (CLOUD MODE) ---")
else:
    OUTPUT_DIR = os.path.abspath("referater_rksk")
    print(f"--- RUNNING LOCALLY ---")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


def create_cover_page(participants, date_text):
    """
    Generates a single PDF page in memory containing the list of participants.
    """
    packet = BytesIO()
    # Create a canvas (A4 size)
    c = canvas.Canvas(packet, pagesize=A4)

    # Draw Title
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 800, "Referat: Økonomiudvalget")
    c.setFont("Helvetica", 12)
    c.drawString(50, 780, f"Dato: {date_text}")

    # Draw Participants Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 740, "Deltagere:")

    # Draw Names
    c.setFont("Helvetica", 12)
    y_position = 715

    if participants:
        for person in participants:
            # Bullet point list
            c.drawString(70, y_position, f"• {person}")
            y_position -= 20  # Move down for next name
    else:
        c.drawString(70, y_position, "(Ingen deltagere fundet på dagsordenen)")

    c.save()

    # Move buffer to beginning so pypdf can read it
    packet.seek(0)
    return packet


def get_meeting_links():
    print(f"--- Step 1: Fetching meeting list from {START_URL} ---")
    try:
        response = requests.get(START_URL, headers=HEADERS)
        response.encoding = 'utf-8'
        response.raise_for_status()
    except Exception as e:
        print(f"CRITICAL ERROR: Could not connect to site: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    meetings = []

    rows = soup.find_all("tr", class_="agenda--tr")

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        # Check Type (Referat only)
        meeting_type = cols[3].get_text(strip=True).lower()
        if "referat" not in meeting_type:
            continue

        onclick = row.get("onclick")
        if onclick:
            match = re.search(r"top\.location='([^']+)'", onclick)
            if match:
                relative_url = match.group(1)
                full_url = urljoin(BASE_URL, relative_url)

                date_text = cols[1].get_text(strip=True)
                date_obj = None

                # Parse date for filename
                try:
                    date_match = re.search(r"(\d+)\.\s+([a-z]+)\s+(\d{4})", date_text.lower())
                    if date_match:
                        day, month_name, year = date_match.groups()
                        months = {
                            'januar': '01', 'februar': '02', 'marts': '03', 'april': '04',
                            'maj': '05', 'juni': '06', 'juli': '07', 'august': '08',
                            'september': '09', 'oktober': '10', 'november': '11', 'december': '12'
                        }
                        month_num = months.get(month_name, '01')
                        filename = f"{year}-{month_num}-{day.zfill(2)}_rksk_oekonomiudvalget.pdf"
                        date_obj = datetime.date(int(year), int(month_num), int(day))
                    else:
                        filename = f"rksk_unknown_{len(meetings)}.pdf"
                except:
                    filename = f"rksk_unknown_{len(meetings)}.pdf"

                meetings.append({
                    'url': full_url,
                    'filename': filename,
                    'date': date_text,
                    'date_obj': date_obj
                })

    print(f"  > Found {len(meetings)} 'Referat' meetings.")
    return meetings


def get_meeting_data(meeting_url):
    """
    Visits meeting page.
    Returns a tuple: (List of PDF items, List of Participant Names)
    """
    try:
        response = requests.get(meeting_url, headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
    except:
        return [], []

    # --- 1. EXTRACT PARTICIPANTS ---
    participants = []
    # Look for h2 with text "Deltagere"
    deltagere_header = soup.find(lambda tag: tag.name == "h2" and "Deltagere" in tag.get_text())

    if deltagere_header:
        # The list is usually in the parent div -> ul -> li
        parent_card = deltagere_header.find_parent("div", class_="agenda--card")
        if parent_card:
            items = parent_card.find_all("li")
            participants = [li.get_text(strip=True) for li in items]

    # --- 2. EXTRACT PDF LINKS ---
    pdf_items = []
    anchors = soup.find_all("a", href=True)

    for a in anchors:
        href = a['href']
        text = a.get_text(strip=True).lower()
        title_attr = a.get('title', '')
        title_lower = title_attr.lower()

        if "/Edoc/" in href and href.endswith(".pdf"):
            # Exclude full referat
            if "hent hele referat" in text or "hent hele referat" in title_lower:
                continue
            # Exclude dagsorden approval
            if "godkendelse af dagsorden" in text or "godkendelse af dagsorden" in title_lower:
                continue

            # Include print items
            if "print" in text or a.get("id") == "download-pdf":
                clean_href = href.replace('\\', '/')
                full_pdf_url = urljoin(BASE_URL, clean_href)
                clean_title = title_attr.replace("Print ", "").strip() or "Unknown Item"

                if not any(item['url'] == full_pdf_url for item in pdf_items):
                    pdf_items.append({'url': full_pdf_url, 'title': clean_title})

    return pdf_items, participants


def download_and_merge(pdf_items, participants, output_filename, date_text):
    merger = PdfWriter()

    # --- 1. ADD COVER PAGE (Participants) ---
    print("    + Generating Cover Page (Participants)")
    cover_page_pdf = create_cover_page(participants, date_text)
    merger.append(cover_page_pdf)

    # --- 2. ADD AGENDA ITEMS ---
    if not pdf_items:
        print("    > No agenda items found to merge.")
    else:
        count = 0
        for item in pdf_items:
            url = item['url']
            title = item['title']
            print(f"    + Downloading: {title}")

            try:
                r = requests.get(url, headers=HEADERS)
                r.raise_for_status()
                pdf_file = BytesIO(r.content)
                merger.append(pdf_file)
                count += 1
            except Exception as e:
                print(f"      x Error downloading part: {e}")

    # --- 3. SAVE FINAL FILE ---
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    # --- CHECK IF EXISTS (Cloud or Local) ---
    if IS_RENDER:
        s3 = scraper_utils.get_s3_client()
        if s3:
            try:
                s3.head_object(Bucket=WASABI_BUCKET, Key=output_filename)
                print(f"Skipping {output_filename} (Already in Wasabi)")
                return True
            except:
                pass
    elif os.path.exists(output_path):
        # print(f"Skipping {output_filename} (Exists locally)")
        return True

    with open(output_path, "wb") as fout:
        merger.write(fout)
    
    # --- UPLOAD IF ON RENDER ---
    if IS_RENDER:
        scraper_utils.upload_to_wasabi(output_path, WASABI_BUCKET, output_filename)
        if os.path.exists(output_path):
            os.remove(output_path)
    else:
        print(f"  > SUCCESS: Saved {output_filename}")
        
    return True


def run_scraper():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("--- Starting Ringkøbing-Skjern Scraper ---")
    meetings = get_meeting_links()
    
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

        print(f"\n[{i + 1}/{len(meetings)}] Processing: {meeting['date']}")

        # Get both PDF links AND Participant names
        pdf_items, participants = get_meeting_data(meeting['url'])

        # Pass everything to the merger
        if download_and_merge(pdf_items, participants, meeting['filename'], meeting['date']):
            processed_count += 1

    print("--- Job Complete ---")


if __name__ == "__main__":
    run_scraper()