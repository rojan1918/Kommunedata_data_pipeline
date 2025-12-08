import requests
import concurrent.futures

# --- CONFIGURATION ---
# We pretend to be a real browser to avoid being blocked by firewalls
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# --- BASE NAMES OF MUNICIPALITIES ---
MUNICIPALITIES_STEMS = [
    "aabenraa", "aalborg", "aarhus", "aeroe", "albertslund", "alleroed",
    "assens", "ballerup", "billund", "brk", "brondby", "bronderslev",
    "dragoer", "gedal", "esbjerg", "fanoe", "favrskov", "faxe",
    "fredensborg", "fredericia", "frederiksberg", "frederikshavn",
    "frederikssund", "furesoe", "fmk", "gentofte", "gladsaxe", "glostrup",
    "greve", "gribskov", "guldborgsund", "haderslev", "halsnaes",
    "hedensted", "helsingor", "herlev", "herning", "hillerod", "hjoerring",
    "holbaek", "holstebro", "horsens", "horsholm", "hvidovre", "htk",
    "ikast-brande", "ishoj", "jammerbugt", "kalundborg", "kerteminde",
    "kk", "koege", "kolding", "laesoe", "langeland", "lejre", "lemvig",
    "lolland", "ltk", "mariagerfjord", "middelfart", "morsoe", "naestved",
    "norddjurs", "nordfyns", "nyborg", "odder", "odense", "odsherred",
    "randers", "rebild", "ringkobing-skjern", "ringsted", "roskilde",
    "rudersdal", "rk", "samsoe", "silkeborg", "skanderborg", "skive",
    "slagelse", "solrod", "soroe", "stevns", "struer", "svendborg",
    "syddjurs", "sonderborg", "taarnby", "thisted", "toender", "vallensbaek",
    "varde", "vejen", "vejle", "vesthimmerland", "viborg", "vordingborg"
]


def check_url(url):
    """
    Checks a single URL with proper headers.
    Retries with GET if HEAD fails.
    """
    try:
        # Attempt 1: HEAD request (Fast)
        # Allow redirects is key because dagsordener.x often redirects to www.dagsordener.x
        response = requests.head(url, headers=HEADERS, timeout=5, allow_redirects=True)

        if response.status_code < 400:
            return response.url.rstrip('/')

        # Attempt 2: If HEAD returns 404 or 405 (Method Not Allowed), try GET (Slower but safer)
        if response.status_code in [404, 405, 403]:
            # Only retry if it's a "soft" fail.
            # Sometimes 403 (Forbidden) is just blocking HEAD.
            response = requests.get(url, headers=HEADERS, timeout=5)
            if response.status_code < 400:
                return response.url.rstrip('/')

    except requests.exceptions.RequestException:
        pass
    return None


def scan_municipality_variations(name):
    """
    Generates 4 variations for a municipality name and checks them.
    """
    variations = []
    prefixes = ["dagsordener", "dagsordner", "dagsorden"]  # Catch spelling errors
    suffixes = [".dk", "kommune.dk"]

    for prefix in prefixes:
        for suffix in suffixes:
            variations.append(f"https://{prefix}.{name}{suffix}")

    found_urls = set()

    for url in variations:
        valid_url = check_url(url)
        if valid_url:
            found_urls.add(valid_url)

    return list(found_urls)


def find_all_portals():
    unique_final_portals = set()
    print(f"--- Starting Comprehensive Scan (With Headers) ---")
    print(f"Checking {len(MUNICIPALITIES_STEMS)} names with 4 variations each...")

    # Slightly slower workers to avoid triggering rate limits on shared hostings
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_name = {
            executor.submit(scan_municipality_variations, name): name
            for name in MUNICIPALITIES_STEMS
        }

        for future in concurrent.futures.as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results = future.result()
                if results:
                    for url in results:
                        # Clean up the URL to ensure uniqueness
                        clean_url = url.rstrip('/')
                        if clean_url not in unique_final_portals:
                            print(f"[MATCH] {name.ljust(15)} -> {clean_url}")
                            unique_final_portals.add(clean_url)
            except Exception as exc:
                print(f"Error checking {name}: {exc}")

    return sorted(list(unique_final_portals))


if __name__ == "__main__":
    active_portals = find_all_portals()

    print("\n" + "=" * 60)
    print(f"SCAN COMPLETE. Found {len(active_portals)} unique FirstAgenda portals.")
    print("=" * 60)

    with open("all_municipality_urls.txt", "w") as f:
        for url in active_portals:
            f.write(url + "\n")

    print("\nUnique list saved to 'all_municipality_urls.txt'")