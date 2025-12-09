# Project Structure

## Directory Layout
```
to-currency-scrapper/
├── app.py                      # Main scraper application
├── requirements.txt            # Python dependencies
├── dockerfile                  # Container image definition
├── docker-compose.yml          # Local development orchestration
├── build.sh                    # Build automation script
├── test_docker.sh              # Local container testing script
├── .env.example                # Environment variables template
├── playwright_sessions/        # Persistent browser session storage
│   └── storage_state.json      # Playwright cookies and auth state
├── README.md                   # Quick start guide
├── YANDEX_CLOUD_SETUP.md      # Detailed cloud deployment guide
├── DEPLOY.md                   # Deployment instructions
└── CHANGELOG.md                # Version history
```

## Core Components

### app.py
Single-file application containing:
- **PlaywrightHelper**: Async class for browser automation with stealth features
- **CurrencyScraperError**: Custom exception for scraping failures
- **Storage State Management**: Functions for syncing authentication with Yandex Object Storage
- **Scraping Logic**: Main execution flow for extracting currency rates
- **Email/API Integration**: Result delivery mechanisms

### Configuration Files
- **dockerfile**: Multi-stage build using official Playwright Python image (v1.49.0-jammy)
- **requirements.txt**: Pinned dependencies (requests, playwright, beautifulsoup4, boto3)
- **.env**: Runtime configuration (emails, API URLs, storage credentials)

### Session Persistence
- **playwright_sessions/**: Local directory for browser state
- **storage_state.json**: Serialized cookies/localStorage synced with cloud storage

## Architectural Patterns

### Hybrid Scraping Architecture
- **Playwright Path**: For sites requiring JavaScript execution (tour-kassa)
  - Launches headless Chromium with anti-detection measures
  - Loads persistent storage state for authenticated sessions
  - Saves updated state after successful scraping
- **Requests Path**: For static HTML sites
  - Uses requests.Session for efficient HTTP calls
  - BeautifulSoup for HTML parsing

### Cloud-Native Design
- **Stateless Execution**: Downloads authentication state from Object Storage on startup
- **State Synchronization**: Uploads updated state after successful runs
- **Graceful Degradation**: Falls back to local state if cloud storage unavailable
- **Resource Optimization**: Chromium configured for 2GB memory containers

### Error Handling Strategy
- Custom exceptions for scraping failures
- Logging at INFO level for operational visibility
- Validation of storage state JSON before use
- Suppression of non-critical errors (file cleanup)
