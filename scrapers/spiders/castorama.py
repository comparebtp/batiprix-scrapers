"""Spider for Castorama France - castorama.fr

Strategy:
- Use Playwright for JS rendering (React SPA, aggressive Cloudflare)
- Extract from dataLayer (Google Analytics ecommerce events)
- Fallback to DOM parsing
- Crawl from sitemap categories
"""
import json
import scrapy
try:
    from scrapy_playwright.page import PageMethod
except ImportError:
    PageMethod = None  # Playwright not installed
from scrapers.spiders.base import BaseBTPSpider


class CastoramaSpider(BaseBTPSpider):
    name = 'castorama'
    store_chain = 'castorama'
    allowed_domains = ['castorama.fr']

    start_categories = [
        # Outillage
        '/outillage/c/cat20006',
        '/outillage/outillage-a-main/c/cat700087',
        '/outillage/outillage-electroportatif/c/cat700085',
        '/outillage/rangement-d-atelier/c/cat700174',
        '/outillage/equipement-du-bricoleur/c/cat700170',
        # Quincaillerie
        '/quincaillerie-securite/c/cat20010',
        '/quincaillerie-securite/visserie-boulonnerie/c/cat700093',
        '/quincaillerie-securite/fixation/c/cat700091',
        '/quincaillerie-securite/serrure-verrou/c/cat700095',
        # Peinture
        '/peinture-droguerie/c/cat20008',
        '/peinture-droguerie/peinture-interieure/c/cat700059',
        '/peinture-droguerie/peinture-exterieure/c/cat700061',
        '/peinture-droguerie/lasure-vernis/c/cat700063',
        '/peinture-droguerie/enduit-preparation/c/cat700065',
        # Électricité
        '/electricite-domotique/c/cat20004',
        '/electricite-domotique/cable-gaine-fil/c/cat700029',
        '/electricite-domotique/tableau-electrique/c/cat700033',
        '/electricite-domotique/appareillage-electrique/c/cat700031',
        '/electricite-domotique/eclairage/c/cat700027',
        # Plomberie
        '/plomberie-chauffage/c/cat20009',
        '/plomberie-chauffage/robinetterie/c/cat700071',
        '/plomberie-chauffage/sanitaire/c/cat700073',
        '/plomberie-chauffage/chauffage/c/cat700069',
        '/plomberie-chauffage/tuyauterie-raccord/c/cat700075',
        # Matériaux
        '/materiaux-gros-oeuvre/c/cat20007',
        '/materiaux-gros-oeuvre/isolation/c/cat700049',
        '/materiaux-gros-oeuvre/cloison-plaque-de-platre/c/cat700051',
        '/materiaux-gros-oeuvre/bois-panneau/c/cat700047',
        '/materiaux-gros-oeuvre/menuiserie/c/cat700053',
        # Sol & Mur
        '/carrelage-sol-mur/c/cat20003',
        '/carrelage-sol-mur/carrelage/c/cat700013',
        '/carrelage-sol-mur/parquet-stratifie/c/cat700015',
        # Salle de bains
        '/salle-de-bains/c/cat20011',
        # Jardin
        '/jardin-terrasse/c/cat20005',
        '/jardin-terrasse/cloture-grillage/c/cat700039',
        '/jardin-terrasse/terrasse/c/cat700041',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 4,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': 45000,
    }

    def start_requests(self):
        for cat_path in self.start_categories:
            url = f'https://www.castorama.fr{cat_path}'
            cat_name = cat_path.split('/')[1] if '/' in cat_path else 'unknown'
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={
                    'playwright': True,
                    'playwright_include_page': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_load_state', 'networkidle'),
                        PageMethod('wait_for_timeout', 3000),
                    ],
                    'category_path': [cat_name],
                },
                errback=self.errback_close_page,
            )

    async def parse_category(self, response):
        page = response.meta.get('playwright_page')
        category_path = response.meta.get('category_path', [])

        try:
            # Extract from dataLayer (GA ecommerce)
            datalayer_products = await page.evaluate('''
                () => {
                    if (!window.dataLayer) return [];
                    const products = [];
                    for (const entry of window.dataLayer) {
                        const ecom = entry.ecommerce;
                        if (ecom) {
                            const items = ecom.impressions || ecom.items ||
                                         (ecom.productListItems) || [];
                            for (const item of items) {
                                products.push({
                                    name: item.name || item.item_name || '',
                                    price: item.price || item.item_price || 0,
                                    sku: item.id || item.item_id || '',
                                    brand: item.brand || item.item_brand || '',
                                    category: item.category || item.item_category || '',
                                });
                            }
                        }
                    }
                    return products;
                }
            ''')

            for product in (datalayer_products or []):
                if product.get('name') and product.get('price'):
                    yield self.make_item(
                        product_name=product['name'],
                        sku=str(product.get('sku', '')),
                        manufacturer=product.get('brand', ''),
                        price=product['price'],
                        category_path=category_path + [product.get('category', '')],
                    )

            # If dataLayer was empty, try DOM parsing
            if not datalayer_products:
                dom_products = await page.evaluate('''
                    () => {
                        const products = [];
                        const cards = document.querySelectorAll(
                            '[class*="product-card"], [class*="ProductCard"], ' +
                            '[data-testid*="product"], article[class*="product"]'
                        );
                        cards.forEach(card => {
                            const nameEl = card.querySelector('h2, h3, [class*="title"], [class*="name"]');
                            const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                            const linkEl = card.querySelector('a[href*="/p/"]');
                            const imgEl = card.querySelector('img');
                            if (nameEl && priceEl) {
                                products.push({
                                    name: nameEl.textContent.trim(),
                                    price: priceEl.textContent.trim(),
                                    url: linkEl ? linkEl.href : '',
                                    image: imgEl ? (imgEl.src || '') : '',
                                });
                            }
                        });
                        return products;
                    }
                ''')

                for product in (dom_products or []):
                    price = self.parse_price(product.get('price', ''))
                    if product.get('name') and price:
                        yield self.make_item(
                            product_name=product['name'],
                            product_url=product.get('url', ''),
                            price=price,
                            image_url=product.get('image', ''),
                            category_path=category_path,
                        )

            # Subcategories
            subcats = await page.evaluate('''
                () => {
                    const links = [];
                    document.querySelectorAll(
                        'a[href*="/c/cat"], a[href*="/c/CAT"]'
                    ).forEach(a => {
                        if (a.textContent.trim()) {
                            links.push({href: a.href, text: a.textContent.trim()});
                        }
                    });
                    return links;
                }
            ''')

            seen_urls = set()
            for subcat in (subcats or []):
                href = subcat.get('href', '')
                if href and href not in seen_urls and href != response.url:
                    seen_urls.add(href)
                    yield scrapy.Request(
                        href,
                        callback=self.parse_category,
                        meta={
                            'playwright': True,
                            'playwright_include_page': True,
                            'playwright_page_methods': [
                                PageMethod('wait_for_load_state', 'networkidle'),
                                PageMethod('wait_for_timeout', 3000),
                            ],
                            'category_path': category_path + [subcat.get('text', '')],
                        },
                        errback=self.errback_close_page,
                    )

            # Pagination
            next_page = await page.evaluate('''
                () => {
                    const next = document.querySelector(
                        'a[rel="next"], a[aria-label*="Suivant"], ' +
                        'a[aria-label*="suivant"], [class*="pagination"] a[class*="next"]'
                    );
                    return next ? next.href : null;
                }
            ''')

            if next_page:
                yield scrapy.Request(
                    next_page,
                    callback=self.parse_category,
                    meta={
                        'playwright': True,
                        'playwright_include_page': True,
                        'playwright_page_methods': [
                            PageMethod('wait_for_load_state', 'networkidle'),
                            PageMethod('wait_for_timeout', 3000),
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
