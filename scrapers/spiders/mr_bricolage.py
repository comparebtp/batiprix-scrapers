"""Spider for Mr Bricolage - mr-bricolage.fr

Strategy: Category crawl with Playwright rendering (required).
The site uses aggressive Cloudflare + Datadome anti-bot protection.
Headless browsers are detected; requires scrapy-playwright with stealth settings.
robots.txt blocks ClaudeBot, GPTBot, etc. but allows generic User-agent: *.
shopId S1638 = Nice store.

JSON-LD: Expected to have Product type (standard for modern e-commerce).
This spider requires scrapy-playwright to be installed:
    pip install scrapy-playwright
    playwright install chromium

Note: ROBOTSTXT_OBEY is False because the Cloudflare challenge page
intercepts the robots.txt fetch from Scrapy. The actual robots.txt
allows generic user agents (User-agent: * / Allow: /).
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class MrBricolageSpider(BaseBTPSpider):
    name = 'mr_bricolage'
    store_chain = 'mr_bricolage'
    allowed_domains = ['mr-bricolage.fr']

    # Nice store
    SHOP_ID = 'S1638'

    custom_settings = {
        'DOWNLOAD_DELAY': 3.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'ROBOTSTXT_OBEY': False,  # Cloudflare blocks robots.txt fetch
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        },
        'RETRY_TIMES': 3,
        'RETRY_HTTP_CODES': [403, 429, 500, 502, 503],
    }

    @classmethod
    def update_settings(cls, settings):
        """Inject Playwright settings if scrapy-playwright is installed."""
        super().update_settings(settings)
        if _has_playwright():
            settings.set('DOWNLOAD_HANDLERS', {
                'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
            }, priority='spider')
            settings.set('PLAYWRIGHT_BROWSER_TYPE', 'chromium', priority='spider')
            settings.set('PLAYWRIGHT_LAUNCH_OPTIONS', {
                'headless': False,  # Cloudflare detects headless
                'args': ['--disable-blink-features=AutomationControlled'],
            }, priority='spider')

    # Category URLs for Mr Bricolage
    START_CATEGORIES = [
        'https://www.mr-bricolage.fr/outillage-bricolage.html',
        'https://www.mr-bricolage.fr/electricite-domotique.html',
        'https://www.mr-bricolage.fr/plomberie-chauffage.html',
        'https://www.mr-bricolage.fr/quincaillerie.html',
        'https://www.mr-bricolage.fr/peinture-droguerie.html',
        'https://www.mr-bricolage.fr/materiaux-menuiserie.html',
        'https://www.mr-bricolage.fr/carrelage-revetement-sol.html',
        'https://www.mr-bricolage.fr/salle-de-bains-wc.html',
    ]

    def start_requests(self):
        """Start with category pages using Playwright for rendering."""
        use_playwright = _has_playwright()

        for url in self.START_CATEGORIES:
            meta = {'depth': 0}
            if use_playwright:
                meta['playwright'] = True
                meta['playwright_page_methods'] = [
                    {'method': 'wait_for_timeout', 'args': [5000]},
                ]
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta=meta,
                dont_filter=True,
            )

    def parse_category(self, response):
        """Extract product links from category page."""
        if response.status == 403 or b'securise votre navigation' in response.body[:2000]:
            self.logger.warning(f"Blocked by anti-bot on {response.url}")
            return

        depth = response.meta.get('depth', 0)
        use_playwright = _has_playwright()

        # Product links
        product_links = set()
        for link in response.css('a::attr(href)').getall():
            full_url = response.urljoin(link)
            if (
                'mr-bricolage.fr/' in full_url
                and full_url.endswith('.html')
                and '/checkout/' not in full_url
                and '/customer/' not in full_url
                and '/catalogsearch/' not in full_url
                and 'securise' not in full_url
            ):
                product_links.add(full_url)

        self.logger.info(f"Category {response.url}: {len(product_links)} links")

        for url in product_links:
            meta = {}
            if use_playwright:
                meta['playwright'] = True
                meta['playwright_page_methods'] = [
                    {'method': 'wait_for_timeout', 'args': [3000]},
                ]
            yield scrapy.Request(url, callback=self.parse_product, meta=meta)

        # Pagination
        next_page = response.css('a[rel="next"]::attr(href)').get()
        if not next_page:
            next_page = response.css(
                'li.pages-item-next a::attr(href), '
                'a.action.next::attr(href), '
                'a[title="Suivant"]::attr(href), '
                'a[title="Page suivante"]::attr(href)'
            ).get()

        if next_page:
            meta = {'depth': depth}
            if use_playwright:
                meta['playwright'] = True
                meta['playwright_page_methods'] = [
                    {'method': 'wait_for_timeout', 'args': [5000]},
                ]
            yield response.follow(next_page, callback=self.parse_category, meta=meta)

        # Subcategories (max depth 2)
        if depth < 2:
            for link in response.css('a::attr(href)').getall():
                full_url = response.urljoin(link)
                if (
                    'mr-bricolage.fr/' in full_url
                    and full_url.endswith('.html')
                    and '/checkout/' not in full_url
                    and '/customer/' not in full_url
                    and '?' not in full_url
                    and full_url != response.url
                ):
                    meta = {'depth': depth + 1}
                    if use_playwright:
                        meta['playwright'] = True
                        meta['playwright_page_methods'] = [
                            {'method': 'wait_for_timeout', 'args': [5000]},
                        ]
                    yield scrapy.Request(
                        full_url,
                        callback=self.parse_category,
                        meta=meta,
                    )

    def parse_product(self, response):
        """Extract product data from JSON-LD or HTML."""
        if response.status == 403 or b'securise votre navigation' in response.body[:2000]:
            self.logger.warning(f"Product blocked: {response.url}")
            return

        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()

        # BreadcrumbList
        category = []
        for script in scripts:
            try:
                data = json.loads(script)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'BreadcrumbList':
                            data = item
                            break
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    for item in data.get('itemListElement', []):
                        name = item.get('name', '').strip()
                        if name:
                            category.append(name)
            except (json.JSONDecodeError, ValueError):
                pass

        # Product JSON-LD
        for script in scripts:
            try:
                data = json.loads(script)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product':
                            data = item
                            break
                    else:
                        continue
                if data.get('@type') != 'Product':
                    continue

                name = data.get('name', '').strip()
                if not name:
                    continue

                offers = data.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get('price')
                if not price:
                    continue
                price = float(price)

                ean = data.get('gtin13') or data.get('gtin') or ''
                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')
                sku = data.get('sku', '')
                mpn = data.get('mpn', '')

                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                desc = data.get('description', '')[:500] if data.get('description') else ''

                yield self.make_item(
                    product_name=name,
                    product_url=response.url,
                    sku=sku or None,
                    ean=ean or None,
                    manufacturer=brand or None,
                    manufacturer_ref=mpn or None,
                    price=price,
                    image_url=image or None,
                    description=desc or None,
                    category_path=category or None,
                    in_stock=offers.get('availability', '').endswith('InStock'),
                )
                return

            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        # Fallback: meta tags + DOM
        self._parse_product_fallback(response, category)

    def _parse_product_fallback(self, response, category):
        """Fallback extraction from meta tags and DOM."""
        name = (
            response.css('meta[property="og:title"]::attr(content)').get()
            or response.css('h1.page-title span::text, h1::text, h1.product-name::text').get()
        )
        if not name:
            return
        name = name.strip()

        price_str = (
            response.css('meta[property="product:price:amount"]::attr(content)').get()
            or response.css('span[data-price-type="finalPrice"]::attr(data-price-amount)').get()
            or response.css('.price-wrapper::attr(data-price-amount)').get()
            or response.css('span.price::text, .product-info-price .price::text').get()
        )
        price = self.parse_price(price_str)
        if not price:
            return

        image = response.css('meta[property="og:image"]::attr(content)').get()
        brand = response.css('meta[property="product:brand"]::attr(content)').get()

        sku = response.css(
            'div[itemprop="sku"]::text, '
            '.product.attribute.sku .value::text, '
            'span[itemprop="sku"]::text'
        ).get()

        ean = response.css(
            'span[itemprop="gtin13"]::text, '
            'span[itemprop="gtin"]::text'
        ).get()

        desc = response.css('meta[property="og:description"]::attr(content)').get()
        if desc:
            desc = desc[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku.strip() if sku else None,
            ean=ean.strip() if ean else None,
            manufacturer=brand or None,
            price=price,
            image_url=image or None,
            description=desc or None,
            category_path=category or None,
        )


def _has_playwright():
    """Check if scrapy-playwright is installed."""
    try:
        import scrapy_playwright  # noqa: F401
        return True
    except ImportError:
        return False
