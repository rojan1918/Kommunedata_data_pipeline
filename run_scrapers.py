import os
import glob
import subprocess
import time
import sys
import scraper

def main():
    print("=========================================")
    print("STARTING DATA PIPELINE")
    print("=========================================")
    
    # 1. Identify Scrapers
    all_files = glob.glob("scraper*.py")
    
    # Exclude utilities and this script if it were named scraper_something (it's run_scrapers.py)
    # Exclude scraper_utils.py
    scrapers = [f for f in all_files if f != "scraper_utils.py"]
    
    # Sort to ensure consistent order (optional, but good for logs)
    scrapers.sort()
    
    # 2. Filter by Municipality if MUNICIPALITY_FILTER is set
    target_filter = os.environ.get("MUNICIPALITY_FILTER")
    if target_filter:
        print(f"Applying filter: '{target_filter}'")

        # Check CSV (generic scraper) for a match (case-insensitive)
        has_generic_match = False
        try:
            targets = scraper.get_municipalities_from_file()
            for target in targets:
                base_url = target['base_url']
                muni_name = scraper.extract_name_from_url(base_url)
                if target_filter.upper() in muni_name.upper():
                    has_generic_match = True
                    break
        except Exception:
            pass

        # Case-insensitive match on filenames for specific scrapers
        scrapers = [s for s in scrapers if target_filter.lower() in s.lower()]

        # If CSV matched, ensure generic scraper runs
        if has_generic_match and "scraper.py" not in scrapers:
            scrapers.append("scraper.py")

        if not scrapers:
            print(f"No scrapers found matching '{target_filter}'")
            return

    print(f"Found {len(scrapers)} scrapers: {', '.join(scrapers)}\n")

    start_time_total = time.time()
    success_count = 0
    fail_count = 0

    for script in scrapers:
        print(f">>> LAUNCHING: {script}")
        script_start = time.time()
        
        try:
            # Run as a separate process to ensure full isolation (memory, Selenium instance, etc.)
            # Pass current environment variables (important for RENDER, WASABI keys)
            result = subprocess.run(
                [sys.executable, script],
                capture_output=False, # Let stdout flow to the logs so we see progress in real-time
                text=True,
                env=os.environ.copy()
            )
            
            duration = time.time() - script_start
            
            if result.returncode == 0:
                print(f">>> SUCCESS: {script} (Time: {duration:.2f}s)\n")
                success_count += 1
            else:
                print(f"!!! FAILURE: {script} exited with code {result.returncode} (Time: {duration:.2f}s)\n")
                fail_count += 1
                
        except Exception as e:
            print(f"!!! CRITICAL ERROR executing {script}: {e}\n")
            fail_count += 1

    total_duration = time.time() - start_time_total
    
    print("=========================================")
    print(f"PIPELINE COMPLETE")
    print(f"Total Time: {total_duration:.2f}s")
    print(f"Successful: {success_count}")
    print(f"Failed:     {fail_count}")
    print("=========================================")

if __name__ == "__main__":
    main()