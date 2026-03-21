"""Spider for Bricomarché - bricomarche.com

Cloudflare protection but passes with Playwright headed mode.
Categories: /c/CATEGORY/CODE
"""
import re
import scrapy
from scrapy_playwright.page import PageMethod
from scrapers.spiders.base import BaseBTPSpider


class BricomarcheSpider(BaseBTPSpider):
    name = 'bricomarche'
    store_chain = 'bricomarche'
    allowed_domains = ['bricomarche.com']

    start_categories = [
        # Outillage
        ('/c/outillage/em10', 'Outillage'),
        ('/c/outillage/electroportatif/em10006', 'Électroportatif'),
        ('/c/outillage/outillage-a-main/em10010', 'Outillage à main'),
        ('/c/outillage/outillage-specialise/em10011', 'Outillage spécialisé'),
        ('/c/outillage/atelier-et-equipement-de-chantier/em10003', 'Atelier et chantier'),
        ('/c/outillage/compresseur-et-accessoires/em10005', 'Compresseur'),
        ('/c/outillage/mesure-et-tracage/em10009', 'Mesure et traçage'),
        # Peinture & Droguerie
        ('/c/peinture-et-droguerie/em11', 'Peinture et droguerie'),
        ('/c/peinture-et-droguerie/peinture/em11001', 'Peinture'),
        # Quincaillerie
        ('/c/quincaillerie/em12', 'Quincaillerie'),
        ('/c/quincaillerie/visserie-boulonnerie/em12004', 'Visserie'),
        ('/c/quincaillerie/fixation/em12002', 'Fixation'),
        # Électricité
        ('/c/electricite/em04', 'Électricité'),
        # Plomberie
        ('/c/plomberie/em09', 'Plomberie'),
        # Matériaux
        ('/c/materiaux/em08', 'Matériaux'),
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
        for path, cat_name in self.start_categories:
            url = f'https://www.bricomarche.com{path}'
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={
                    'playwright': True,
                    'playwright_include_page': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_load_state', 'domcontentloaded'),
                        PageMethod('wait_for_timeout', 5000),
                    ],
                    'category_path': [cat_name],
                },
                errback=self.errback_close_page,
            )

    async def parse_category(self, response):
        page = response.meta.get('playwright_page')
        category_path = response.meta.get('category_path', [])

        try:
            # Accept cookies if present
            try:
                cookie_btn = page.locator('button:has-text("Accepter"), button:has-text("accepter"), [id*=accept]').first()
                if await cookie_btn.count() > 0:
                    await cookie_btn.click(timeout=2000)
                    await page.wait_for_timeout(1000)
            except:
                pass

            # Extract products
            products = await page.evaluate('''() => {
                const items = [];
                // Try various product card selectors
                const selectors = [
                    '.product-card', '.ProductCard', '[class*=product-item]',
                    '[class*=ProductTile]', 'article[class*=product]',
                    '[data-product]', '.product-list-item',
                ];

                let cards = [];
                for (const sel of selectors) {
                    cards = document.querySelectorAll(sel);
                    if (cards.length > 0) break;
                }

                cards.forEach(card => {
                    const nameEl = card.querySelector('[class*=name], [class*=title], h2, h3, h4');
                    const priceEl = card.querySelector('[class*=price], [class*=Price]');
                    const linkEl = card.querySelector('a[href]');
                    const imgEl = card.querySelector('img');

                    if (nameEl) {
                        items.push({
                            name: nameEl.textContent.trim(),
                            price: priceEl ? priceEl.textContent.trim() : '',
                            url: linkEl ? linkEl.href : '',
                            img: imgEl ? (imgEl.src || imgEl.dataset.src || '') : '',
                            sku: card.dataset.productId || card.dataset.sku || '',
                        });
                    }
                });
                return items;
            }''')

            self.logger.info(f"Found {len(products)} products on {response.url}")

            for product in (products or []):
                name = product.get('name', '').strip()
                if not name or len(name) < 3:
                    continue

                price = self.parse_price(product.get('price', ''))

                if price is not None:
                    yield self.make_item(
                        product_name=name,
                        product_url=product.get('url', ''),
                        sku=product.get('sku', ''),
                        price=price,
                        image_url=product.get('img', ''),
                        category_path=category_path,
                    )

            # Subcategories
            subcats = await page.evaluate('''() => {
                const links = [];
                const seen = new Set();
                document.querySelectorAll('a[href*="/c/"]').forEach(a => {
                    if (!seen.has(a.href) && a.textContent.trim().length > 2) {
                        seen.add(a.href);
                        links.push({href: a.href, text: a.textContent.trim()});
                    }
                });
                return links.slice(0, 30);
            }''')

            for subcat in (subcats or []):
                href = subcat.get('href', '')
                if href and href != response.url and '/c/' in href:
                    yield scrapy.Request(
                        href,
                        callback=self.parse_category,
                        meta={
                            'playwright': True,
                            'playwright_include_page': True,
                            'playwright_page_methods': [
                                PageMethod('wait_for_load_state', 'domcontentloaded'),
                                PageMethod('wait_for_timeout', 5000),
                            ],
                            'category_path': category_path + [subcat.get('text', '')],
                        },
                        errback=self.errback_close_page,
                    )

            # Pagination
            next_page = await page.evaluate('''() => {
                const next = document.querySelector(
                    'a[rel="next"], [class*=pagination] a[class*=next], a[aria-label*="Suivant"]'
                );
                return next ? next.href : null;
            }''')

            if next_page:
                yield scrapy.Request(
                    next_page,
                    callback=self.parse_category,
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

    async def errback_close_page(self, failure):
        page = failure.request.meta.get('playwright_page')
        if page:
            await page.close()
        self.logger.error(f"Request failed: {failure.value}")
