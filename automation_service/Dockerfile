FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application code
COPY . .

# Expose the port
EXPOSE 8082

# Run the server
CMD ["python", "server.py"]

