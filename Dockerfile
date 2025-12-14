# Use Python 3.11-slim
FROM python:3.11-slim

# 1. Install Chromium, Driver, and dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    wget \
    unzip \
    libcairo2 \
    libpango-1.0-0 \
    shared-mime-info \
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

# 5. Copy all project files (respecting .dockerignore)
COPY . .

# 6. Run
CMD ["python", "run_scrapers.py"]