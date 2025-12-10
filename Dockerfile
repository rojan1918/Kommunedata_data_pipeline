# Use Python 3.11-slim
FROM python:3.11-slim

# --- FORCE RENDER MODE ---
ENV RENDER=true

# 1. Install Chromium and Driver
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 2. Set Chrome Environment Variables
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROME_DRIVER=/usr/bin/chromedriver

# 3. Setup App
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scraper_roedovre.py .

CMD ["python", "scraper_roedovre.py"]