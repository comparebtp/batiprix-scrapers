"""Spider for Kiloutou - kiloutou.fr (location matériel BTP)

Needs Playwright (JS-rendered). Search-based approach.
Products show rental prices ("Tarif et durée de location").
"""
import re
import scrapy
from scrapy_playwright.page import PageMethod
from scrapers.spiders.base import BaseBTPSpider


class KiloutouSpider(BaseBTPSpider):
    name = 'kiloutou'
    store_chain = 'kiloutou'
    allowed_domains = ['kiloutou.fr']

    SEARCH_TERMS = [
        'perceuse', 'meuleuse', 'perforateur', 'scie',
        'bétonnière', 'compacteur', 'groupe électrogène',
        'échafaudage', 'nacelle', 'chariot', 'mini pelle',
        'nettoyeur haute pression', 'ponceuse', 'rabot',
        'compresseur', 'cloueur', 'visseuse', 'découpeur',
        'laser', 'niveau', 'aspirateur', 'défonceuse',
        'tronçonneuse', 'broyeur', 'benne',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': False,
            'args': ['--disable-blink-features=AutomationControlled'],
        },
    }

    def start_requests(self):
        for term in self.SEARCH_TERMS:
            url = f'https://www.kiloutou.fr/recherche?q={term}'
            yield scrapy.Request(
                url,
                callback=self.parse_search,
                meta={
                    'playwright': True,
                    'playwright_include_page': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_load_state', 'domcontentloaded'),
                        PageMethod('wait_for_timeout', 5000),
                    ],
                    'category_path': [term.title()],
                },
                errback=self.errback_close_page,
            )

    async def parse_search(self, response):
        page = response.meta.get('playwright_page')
        category_path = response.meta.get('category_path', [])

        try:
            products = await page.evaluate('''() => {
                const items = [];
                const seen = new Set();
                const cards = document.querySelectorAll('[class*=product], [class*=card], [class*=item]');
                for (const c of cards) {
                    const nameEl = c.querySelector('h2,h3,h4,[class*=title],[class*=name],[class*=label]');
                    const priceEl = c.querySelector('[class*=price],[class*=Price],[class*=tarif]');
                    const linkEl = c.querySelector('a[href*="/"]');
                    const imgEl = c.querySelector('img');

                    if (nameEl && priceEl) {
                        const name = nameEl.textContent.trim();
                        if (name.length > 5 && !seen.has(name)) {
                            seen.add(name);
                            const priceText = priceEl.textContent.trim();
                            const priceMatch = priceText.match(/(\d+[.,]\d{2})/);
                            items.push({
                                name: name,
                                price: priceMatch ? priceMatch[1] : priceText,
                                url: linkEl ? linkEl.href : '',
                                img: imgEl ? (imgEl.src || imgEl.dataset.src || '') : '',
                            });
                        }
                    }
                }
                return items;
            }''')

            self.logger.info(f"Found {len(products)} products for '{category_path}'")

            for product in (products or []):
                name = product.get('name', '').strip()
                if not name:
                    continue

                price_str = product.get('price', '')
                price = self.parse_price(price_str)

                yield self.make_item(
                    product_name=name,
                    product_url=product.get('url', ''),
                    price=price,
                    unit_label='€/jour HT (location)',
                    image_url=product.get('img', ''),
                    category_path=category_path,
                    manufacturer='Kiloutou',
                )

        finally:
            if page:
                await page.close()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get('playwright_page')
        if page:
            await page.close()
