# Use Python 3.11 (slim version to save space)
FROM python:3.11-slim

# 1. Install Chrome and Chromedriver
# We use Chromium because it's easier to install on Linux servers than Google Chrome
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 2. Set up the working directory
WORKDIR /app

# 3. Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy your script
COPY scraper_roedovre.py .

# 5. Command to run when the Cron Job starts
CMD ["python", "scraper_roedovre.py"]