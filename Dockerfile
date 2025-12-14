# Use Python 3.11-slim
FROM python:3.11-slim

# 1. Install Chromium, Driver, and dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 2. Set Environment Variables so Selenium finds them automatically
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROME_DRIVER=/usr/bin/chromedriver
ENV PYTHONUNBUFFERED=1

# 3. Set work directory
WORKDIR /app

# 4. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy script
COPY scraper_roedovre.py .
COPY scraper_ishoej.py .
COPY run_scrapers.py .

# 6. Run
CMD ["python", "run_scrapers.py"]