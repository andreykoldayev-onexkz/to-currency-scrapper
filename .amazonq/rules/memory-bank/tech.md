# Technology Stack

## Programming Languages
- **Python 3.x**: Primary language (compatible with Python 3.8+)
- **UTF-8 Encoding**: Explicit encoding declaration for Cyrillic text support

## Core Dependencies
```
requests==2.32.3              # HTTP client for static scraping
playwright==1.49.0            # Browser automation framework
beautifulsoup4==4.12.3        # HTML parsing
lxml==5.3.0                   # XML/HTML parser backend
boto3==1.35.15                # AWS SDK (Yandex Object Storage)
email-validator==2.1.0.post1  # Email validation
python-dotenv                 # Environment variable management
```

## Runtime Environment
- **Base Image**: mcr.microsoft.com/playwright/python:v1.49.0-jammy
- **Browser**: Chromium (installed via Playwright)
- **Container Runtime**: Docker/Podman compatible
- **Cloud Platform**: Yandex Cloud (Functions/Container Registry)

## Development Tools

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run locally
python app.py

# Test with Docker
./test_docker.sh
```

### Container Build
```bash
# Build image
docker build -t currency-scraper .

# Run with environment variables
docker run --env-file .env currency-scraper
```

### Deployment
```bash
# Build for production
./build.sh

# Deploy to Yandex Cloud
# See YANDEX_CLOUD_SETUP.md for detailed instructions
```

## Configuration Management
- **Environment Variables**: Loaded via python-dotenv from .env file
- **Required Variables**:
  - `OUTLOOK_EMAIL`, `OUTLOOK_PASSWORD`: Email credentials
  - `TARGET_EMAIL`: Recipient for scraped data
  - `API_URL`: External API endpoint
  - `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`: Object storage
- **Optional Variables**:
  - `PLAYWRIGHT_HEADLESS=1`: Run browser in headless mode
  - `SELENIUM_WAIT_SECONDS=8`: Page load wait time

## Browser Configuration
Chromium launched with 20+ optimization flags:
- `--disable-dev-shm-usage`: Avoid /dev/shm memory issues
- `--no-sandbox`, `--no-zygote`: Container-safe execution
- `--disable-gpu`, `--disable-webgl`: Reduce resource usage
- `--disable-blink-features=AutomationControlled`: Anti-detection

## Cloud Resources
- **Memory**: 2GB recommended
- **CPU**: 1 vCPU minimum
- **Timeout**: 120+ seconds
- **SHM Size**: 2GB for browser stability
