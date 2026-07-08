from app import CurrencyScraper

url = "https://tour-kassa.ru/%D0%BA%D1%83%D1%80%D1%81%D1%8B-%D0%B2%D0%B0%D0%BB%D1%8E%D1%82-%D1%82%D1%83%D1%80%D0%BE%D0%BF%D0%B5%D1%80%D0%B0%D1%82%D0%BE%D1%80%D0%BE%D0%B2"

scraper = CurrencyScraper()
results = scraper.scrape_tour_kassa_site(url)

print(f"Найдено записей: {len(results)}")
print()

for item in results:
    print(item)

print()
print("Ошибки:")
for error in scraper.errors:
    print(error)