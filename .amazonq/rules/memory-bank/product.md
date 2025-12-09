# Product Overview

## Purpose
Currency scraper for tour operators that extracts exchange rates from multiple websites using Playwright for dynamic content and requests for static pages. Designed to run in containerized environments, specifically optimized for Yandex Cloud deployment.

## Key Features
- **Dual Scraping Strategy**: Uses Playwright for JavaScript-heavy sites (tour-kassa) and requests.Session for static sites
- **Persistent Session Management**: Stores and reuses Playwright cookies/storage state across runs
- **Cloud Storage Integration**: Syncs authentication state with Yandex Object Storage for stateless container deployments
- **Container-Optimized**: Configured with resource-efficient Chromium arguments for limited memory environments (2GB RAM)
- **Email Notifications**: Sends scraped currency data via Outlook SMTP
- **API Integration**: Posts results to external API endpoints (Bitrix24 compatible)
- **Stealth Mode**: Implements anti-detection measures to avoid bot detection

## Target Users
- Tour operators needing automated currency rate monitoring
- DevOps teams deploying scrapers in Yandex Cloud Functions or Container Registry
- Developers building web scraping solutions for containerized environments

## Use Cases
- Automated daily currency rate collection from tour operator websites
- Monitoring exchange rate changes across multiple providers
- Feeding currency data into business intelligence systems
- Running scheduled scraping jobs in serverless cloud environments
