# Development Guidelines

## Code Quality Standards

### File Encoding and Documentation
- Always declare UTF-8 encoding at file start: `# -*- coding: utf-8 -*-`
- Include module-level docstrings explaining purpose and key functionality
- Use Russian language for comments and docstrings (project targets Russian market)
- Triple-quoted strings for docstrings: `'''Description'''` or `"""Description"""`

### Naming Conventions
- **Classes**: PascalCase (e.g., `CurrencyScraperError`, `PlaywrightHelper`, `EmailNotifier`)
- **Functions/Methods**: snake_case (e.g., `scrape_all_sites`, `get_random_headers`, `send_notification`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `SELENIUM_WAIT_SECONDS`, `PLAYWRIGHT_HEADLESS`, `STORAGE_ENDPOINT`)
- **Private Functions**: Prefix with underscore (e.g., `_is_storage_configured`, `_storage_state_is_valid`, `_normalize_operator_name`)
- **Global Singletons**: Prefix with underscore (e.g., `_storage_client`)

### Type Hints
- Use type hints for function parameters and return values
- Import from `typing` module: `Optional`, `Dict`, `List`
- Example pattern:
```python
def refresh_storage_state() -> Optional[Path]:
    ...

def get_random_headers(self) -> Dict[str, str]:
    ...

def scrape_all_sites(self) -> Dict:
    ...
```

## Architectural Patterns

### Hybrid Scraping Strategy
- **Playwright for JavaScript-heavy sites**: Use async Playwright for sites requiring browser execution (tour-kassa.ru)
- **Requests for static sites**: Use requests.Session for simple HTML scraping
- **Decision logic in make_request method**: Route to appropriate scraper based on URL
```python
if 'tour-kassa.ru' in url:
    html = self.playwright.fetch(url, wait_selector='table.mod_rate_today')
else:
    resp = self.session.get(url, headers=headers, timeout=timeout)
```

### Async/Sync Bridge Pattern
- Playwright uses async API, but main code is synchronous
- Provide sync wrapper using `asyncio.run()` with fallback to new event loop:
```python
def fetch(self, url: str) -> Optional[str]:
    try:
        return asyncio.run(self.get_page_html(url))
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(self.get_page_html(url))
        loop.close()
        return result
```

### Resource Management
- Use context managers for cleanup: `async with async_playwright() as p:`
- Suppress non-critical exceptions during cleanup: `with suppress(Exception):`
- Always close browser contexts and browsers in finally blocks
- Validate state before operations (e.g., `_storage_state_is_valid()` before loading)

### Configuration Management
- Load environment variables with `python-dotenv` at module level
- Provide sensible defaults: `os.getenv("KEY", "default_value")`
- Support AWS-compatible fallbacks: `STORAGE_ACCESS_KEY or AWS_ACCESS_KEY_ID`
- Use boolean conversion: `os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"`

## Error Handling

### Logging Strategy
- Use Python's logging module with named logger: `logger = logging.getLogger("scraper")`
- Log levels:
  - `logger.info()`: Successful operations, progress updates
  - `logger.warning()`: Recoverable errors, fallback scenarios
  - `logger.error()`: Failed operations that don't stop execution
  - `logger.debug()`: Detailed debugging information
- Include context in log messages: `f"Starting Playwright for {url}"`

### Retry Logic
- Implement retry loops with configurable attempts (default 3)
- Add exponential backoff: `time.sleep(random.uniform(2, 5))`
- Log each attempt: `logger.warning(f"Attempt {attempt+1} for {url} failed: {e}")`
- Collect errors in list for reporting: `self.errors.append(f"Failed to fetch {url}: {e}")`

### Graceful Degradation
- Return `None` or empty list on failure, don't crash
- Continue processing other sites if one fails
- Validate data before use (e.g., check if soup exists before parsing)
- Provide summary statistics: successful vs failed operations

### Custom Exceptions
- Define domain-specific exceptions: `class CurrencyScraperError(Exception)`
- Use for business logic errors, not infrastructure failures
- Include descriptive messages in Russian

## Web Scraping Patterns

### Anti-Detection Measures
- Rotate user agents from predefined list
- Add random delays: `await asyncio.sleep(random.uniform(wait_seconds, wait_seconds + 3))`
- Set realistic headers: Accept-Language, DNT, Connection
- Inject stealth scripts to hide automation:
```python
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
"""
```
- Use extensive Chromium flags to disable automation detection

### Data Extraction
- Use BeautifulSoup with lxml parser: `BeautifulSoup(html, 'html.parser')`
- Prefer CSS selectors: `soup.select_one('div.class > span')`
- Implement multiple fallback strategies for finding elements
- Extract rates with regex patterns: `r'(\d+[.,]\d+)'`
- Normalize extracted text: `text.strip()`, `re.sub(r'\s+', ' ', name)`

### Site-Specific Scrapers
- One method per site: `scrape_tour_kassa_site()`, `scrape_paks_site()`
- Return standardized data structure (list of dicts with id, sectionId, name, touroperator, rate, percentToCb, delta)
- Handle site-specific quirks (SSL verification, special headers, API endpoints)
- Use configuration-driven approach for tour-kassa with operator mappings

## Cloud Integration

### Stateless Session Management
- Download authentication state from Object Storage on startup: `refresh_storage_state()`
- Upload updated state after successful scraping: `upload_storage_state()`
- Validate JSON before use: `_storage_state_is_valid()`
- Fall back to local state if cloud unavailable
- Use boto3 S3 client with Yandex Cloud endpoint

### Container Optimization
- Launch Chromium with 20+ resource-saving flags
- Disable GPU, WebGL, extensions, background processes
- Use `--disable-dev-shm-usage` for limited /dev/shm
- Set `--no-sandbox` and `--no-zygote` for container safety
- Configure viewport, locale, timezone for consistency

### Environment-Specific Behavior
- Check if storage configured before operations: `if not _is_storage_configured(): return`
- Use global singleton pattern for expensive clients: `_storage_client`
- Log configuration status: "Skipping storage_state upload - storage is not configured"

## Data Processing

### Result Aggregation
- Collect all results in instance variable: `self.results: List[Dict] = []`
- Extend results from each site: `self.results.extend(site_results)`
- Return summary with statistics: total_sites, successful_sites, failed_sites, total_records, errors
- Structure: `{'data': [...], 'summary': {...}}`

### API Integration
- Send results to external API (Bitrix24 workflow)
- Use specific template format: `TEMPLATE_ID`, `DOCUMENT_ID`, `PARAMETERS`
- Batch process with error collection
- Return boolean success indicator
- Set appropriate timeouts: `timeout=120`

### Email Notifications
- Send HTML-formatted reports via SMTP
- Include execution statistics and error details
- Trigger on failures or always (configurable)
- Use MIMEMultipart for structured emails
- Handle notification failures gracefully (don't crash main flow)

## Testing and Debugging

### Debug Logging
- Use `logger.debug()` for verbose output
- Print HTML fragments for inspection: `html_text[:1000]`
- Log intermediate extraction results
- Include search patterns and matches in debug output

### Local Testing
- Support running as script: `if __name__ == "__main__":`
- Provide test script for Docker: `test_docker.sh`
- Use docker-compose for local development
- Test with resource constraints matching production

## Code Organization

### Single-File Architecture
- Keep all code in one file (app.py) for simple deployment
- Group related functionality in classes
- Use module-level constants and functions
- Order: imports → constants → helpers → classes → main function

### Class Responsibilities
- **PlaywrightHelper**: Browser automation and storage state sync
- **CurrencyScraper**: Orchestration and site-specific scrapers
- **EmailNotifier**: SMTP email sending
- Module-level functions for API integration and main entry point

### Method Patterns
- Public methods for external API: `fetch()`, `scrape_all_sites()`
- Private methods for internal logic: `_get_exchange_rates_by_operator()`
- Static methods for pure functions: `_normalize_operator_name()`
- Instance variables for state: `self.session`, `self.results`, `self.errors`
