"""Spider for Loxam - loxam.fr (location matériel BTP)

Needs Playwright (JS-rendered). Homepage shows some prices.
Browse categories for full catalog.
"""
import re
import scrapy
try:
    from scrapy_playwright.page import PageMethod
except ImportError:
    PageMethod = None  # Playwright not installed
from scrapers.spiders.base import BaseBTPSpider


class LoxamSpider(BaseBTPSpider):
    name = 'loxam'
    store_chain = 'loxam'
    allowed_domains = ['loxam.fr']

    SEARCH_TERMS = [
        'perceuse', 'meuleuse', 'bétonnière', 'compacteur',
        'nacelle', 'échafaudage', 'mini pelle', 'chariot',
        'groupe électrogène', 'compresseur', 'nettoyeur',
        'ponceuse', 'scie', 'perforateur', 'cloueur',
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
            url = f'https://www.loxam.fr/recherche?q={term}'
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
                // Look for price patterns in text
                const allText = document.body.innerText;

                // Find product cards
                const cards = document.querySelectorAll('[class*=product], [class*=card], article, [class*=item], [class*=result]');
                for (const c of cards) {
                    const nameEl = c.querySelector('h2,h3,h4,[class*=title],[class*=name],[class*=label]');
                    const priceEl = c.querySelector('[class*=price],[class*=Price],[class*=tarif],[class*=cout]');
                    const linkEl = c.querySelector('a[href]');
                    const imgEl = c.querySelector('img');

                    if (nameEl) {
                        const name = nameEl.textContent.trim();
                        if (name.length > 5 && !seen.has(name)) {
                            seen.add(name);
                            // Find price - look for €
                            let price = '';
                            if (priceEl) {
                                price = priceEl.textContent.trim();
                            } else {
                                // Search in card text for € pattern
                                const cardText = c.textContent;
                                const m = cardText.match(/(\d+[.,]\d{2})\s*€/);
                                if (m) price = m[1] + ' €';
                            }

                            items.push({
                                name: name,
                                price: price,
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

                if price is not None:
                    yield self.make_item(
                        product_name=name,
                        product_url=product.get('url', ''),
                        price=price,
                        unit_label='€/jour HT (location)',
                        image_url=product.get('img', ''),
                        category_path=category_path,
                        manufacturer='Loxam',
                    )

        finally:
            if page:
                await page.close()

    async def errback_close_page(self, failure):
        page = failure.request.meta.get('playwright_page')
        if page:
            await page.close()
