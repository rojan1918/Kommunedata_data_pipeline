import scraper_roedovre
import scraper_ishoej
import time

def main():
    print("=========================================")
    print("STARTING ALL SCRAPERS")
    print("=========================================")
    
    start_time = time.time()
    
    try:
        print("\n>>> STARTING: scraper_roedovre")
        scraper_roedovre.run_roedovre_scraper()
    except Exception as e:
        print(f"!!! ERROR in scraper_roedovre: {e}")

    try:
        print("\n>>> STARTING: scraper_ishoej")
        scraper_ishoej.run_ishoej_scraper()
    except Exception as e:
        print(f"!!! ERROR in scraper_ishoej: {e}")

    elapsed = time.time() - start_time
    print(f"\n=========================================")
    print(f"ALL SCRAPERS FINISHED in {elapsed:.2f} seconds")
    print("=========================================")

if __name__ == "__main__":
    main()
