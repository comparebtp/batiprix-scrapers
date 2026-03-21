"""Spider for Bricorama - bricorama.fr

Cloudflare protection but passes with Playwright headed mode + stealth.
Structure:
- Card: .ProductTile
- Price: "Prix conseillé : XXX € XX"
- Image: img inside card
- Search: /catalogsearch/result/?q=XXX
- Categories navigable
"""
import re
import scrapy
try:
    from scrapy_playwright.page import PageMethod
except ImportError:
    PageMethod = None  # Playwright not installed
from scrapers.spiders.base import BaseBTPSpider


class BricoramaSpider(BaseBTPSpider):
    name = 'bricorama'
    store_chain = 'bricorama'
    allowed_domains = ['bricorama.fr']

    start_categories = [
        '/outillage-c-25.html',
        '/quincaillerie-c-118.html',
        '/peinture-droguerie-c-210.html',
        '/electricite-c-281.html',
        '/plomberie-chauffage-c-400.html',
        '/materiaux-c-328.html',
        '/salle-de-bains-c-462.html',
    ]

    # Also use search for common BTP terms
    SEARCH_TERMS = [
        'perceuse', 'tournevis', 'marteau', 'pince', 'scie',
        'peinture', 'rouleau', 'enduit', 'ciment', 'vis',
        'cable', 'prise', 'robinet', 'carrelage', 'isolation',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': False,
            'args': ['--disable-blink-features=AutomationControlled'],
        },
        'PLAYWRIGHT_CONTEXTS': {
            'default': {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'locale': 'fr-FR',
                'viewport': {'width': 1920, 'height': 1080},
                'java_script_enabled': True,
            }
        },
    }

    def start_requests(self):
        # Search-based approach
        for term in self.SEARCH_TERMS:
            url = f'https://www.bricorama.fr/catalogsearch/result/?q={term}'
            yield scrapy.Request(
                url,
                callback=self.parse_listing,
                meta={
                    'playwright': True,
                    'playwright_include_page': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_load_state', 'domcontentloaded'),
                        PageMethod('wait_for_timeout', 5000),
                    ],
                    'playwright_context_kwargs': {
                        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'locale': 'fr-FR',
                    },
                    'category_path': [term.title()],
                },
                errback=self.errback_close_page,
            )

    async def parse_listing(self, response):
        page = response.meta.get('playwright_page')
        category_path = response.meta.get('category_path', [])

        try:
            products = await page.evaluate('''() => {
                const items = [];
                const cards = document.querySelectorAll('.ProductTile');

                cards.forEach(card => {
                    const nameEl = card.querySelector('.ProductTile-title, [class*=name], h2, h3');
                    const priceEl = card.querySelector('[class*=price], [class*=Price]');
                    const linkEl = card.querySelector('a[href*="/p/"], a[href*="product"]');
                    const imgEl = card.querySelector('img');
                    const refEl = card.querySelector('[class*=ref], [class*=sku]');

                    const priceText = priceEl ? priceEl.textContent.trim() : '';

                    items.push({
                        name: nameEl ? nameEl.textContent.trim() : '',
                        price: priceText,
                        url: linkEl ? linkEl.href : '',
                        img: imgEl ? (imgEl.src || imgEl.dataset.src || '') : '',
                        ref: refEl ? refEl.textContent.trim() : '',
                    });
                });
                return items;
            }''')

            self.logger.info(f"Found {len(products)} products on {response.url}")

            for product in (products or []):
                name = product.get('name', '').strip()
                if not name:
                    continue

                # Parse price: "Prix conseillé : 399 € 00" or "25 € 90"
                price = self._parse_bricorama_price(product.get('price', ''))

                if price is not None:
                    yield self.make_item(
                        product_name=name,
                        product_url=product.get('url', ''),
                        sku=re.sub(r'[^0-9a-zA-Z\-]', '', product.get('ref', '')),
                        price=price,
                        image_url=product.get('img', ''),
                        category_path=category_path,
                    )

            # Pagination
            next_page = await page.evaluate('''() => {
                const next = document.querySelector('a[rel="next"], [class*=pagination] a[class*=next], a[title="Suivant"]');
                return next ? next.href : null;
            }''')

            if next_page:
                yield scrapy.Request(
                    next_page,
                    callback=self.parse_listing,
                    meta={
                        'playwright': True,
                        'playwright_include_page': True,
                        'playwright_page_methods': [
                            PageMethod('wait_for_load_state', 'domcontentloaded'),
                            PageMethod('wait_for_timeout', 5000),
                        ],
                        'category_path': category_path,
                    },
                    errback=self.errback_close_page,
                )

        finally:
            if page:
                await page.close()

    def _parse_bricorama_price(self, price_text):
        """Parse Bricorama price format: 'Prix conseillé : 399 € 00' -> 399.00"""
        if not price_text:
            return None
        # Extract: "399 € 00" or "25 € 90 / m²"
        match = re.search(r'(\d+)\s*€\s*(\d{2})', price_text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        # Fallback
        return self.parse_price(price_text)

    async def errback_close_page(self, failure):
        page = failure.request.meta.get('playwright_page')
        if page:
            await page.close()
        self.logger.error(f"Request failed: {failure.value}")
