"""Spider for Maxoutil - maxoutil.com

Strategy: Sitemap-based + category crawl fallback.
Platform: Magento 2 (Hyva theme) with Cloudflare protection.
JSON-LD: Product with price, brand, sku, description.
Note: gtin8 field in JSON-LD contains internal SKU, NOT real EAN.
~15,000 products. Cloudflare JS challenge on some pages.
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class MaxoutilSpider(BaseBTPSpider):
    name = 'maxoutil'
    store_chain = 'maxoutil'
    allowed_domains = ['maxoutil.com']

    custom_settings = {
        'DOWNLOAD_DELAY': 2.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,  # Cloudflare blocks robots.txt fetch via Scrapy
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
        'RETRY_TIMES': 2,
        'RETRY_HTTP_CODES': [403, 429, 500, 502, 503],
    }

    # Brand pages with BTP-relevant products
    START_CATEGORIES = [
        'https://www.maxoutil.com/makita.html',
        'https://www.maxoutil.com/bosch.html',
        'https://www.maxoutil.com/dewalt.html',
        'https://www.maxoutil.com/metabo.html',
        'https://www.maxoutil.com/hikoki.html',
        'https://www.maxoutil.com/milwaukee.html',
        'https://www.maxoutil.com/festool.html',
        'https://www.maxoutil.com/stanley.html',
        'https://www.maxoutil.com/facom.html',
        'https://www.maxoutil.com/karcher.html',
        'https://www.maxoutil.com/stihl.html',
        'https://www.maxoutil.com/einhell.html',
        # Category pages
        'https://www.maxoutil.com/outillage-electroportatif.html',
        'https://www.maxoutil.com/outillage-a-main.html',
        'https://www.maxoutil.com/equipement-de-chantier.html',
        'https://www.maxoutil.com/visserie-fixation.html',
    ]

    # Fallback product URLs for testing
    start_urls = [
        'https://www.maxoutil.com/makita-ddf489z-perceuse-visseuse-18v-lxt-brushless-sans-batterie.html',
        'https://www.maxoutil.com/bosch-professional-perceuse-visseuse-gsr-18v-55-06019h5202.html',
    ]

    def start_requests(self):
        """Try sitemap first; if blocked by Cloudflare, fall back to categories."""
        self._sitemap_failed = False
        self._category_started = False

        yield scrapy.Request(
            'https://www.maxoutil.com/media/sitemap/sitemap.xml',
            callback=self.parse_sitemap_index,
            errback=self._on_sitemap_fail,
            dont_filter=True,
        )

    def _on_sitemap_fail(self, failure):
        """Sitemap failed, start category crawl."""
        self.logger.warning(f"Sitemap failed: {failure.value}")
        self._sitemap_failed = True
        if not self._category_started:
            yield from self._start_category_crawl()

    def parse_sitemap_index(self, response):
        """Parse sitemap index or direct sitemap."""
        # Check if Cloudflare blocked us
        if response.status == 403 or b'Just a moment' in response.body[:500]:
            self.logger.warning("Sitemap blocked by Cloudflare, falling back to categories")
            self._sitemap_failed = True
            if not self._category_started:
                yield from self._start_category_crawl()
            return

        response.selector.remove_namespaces()

        # Check if sitemap index
        sitemaps = response.xpath('//sitemap/loc/text()').getall()
        if sitemaps:
            self.logger.info(f"Found {len(sitemaps)} sub-sitemaps")
            for url in sitemaps:
                yield scrapy.Request(url, callback=self.parse_sitemap,
                                     errback=self._on_sitemap_fail)
            return

        # Direct sitemap
        yield from self._extract_product_urls(response)

    def parse_sitemap(self, response):
        """Parse a sitemap XML file."""
        if response.status == 403 or b'Just a moment' in response.body[:500]:
            self.logger.warning(f"Sitemap blocked: {response.url}")
            return

        # Handle gzipped sitemaps
        if response.url.endswith('.gz'):
            try:
                import gzip
                body = gzip.decompress(response.body)
                from scrapy.http import TextResponse
                response = TextResponse(url=response.url, body=body, encoding='utf-8')
            except Exception:
                pass

        yield from self._extract_product_urls(response)

    def _extract_product_urls(self, response):
        """Extract product URLs from a sitemap."""
        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Sitemap {response.url}: {len(urls)} URLs")

        product_count = 0
        for url in urls:
            # Magento 2 product URLs end with .html and are flat (no subdirectory)
            if url.endswith('.html'):
                path = url.replace('https://www.maxoutil.com/', '')
                # Skip category-like URLs (contain subdirectories)
                if '/' not in path:
                    product_count += 1
                    yield scrapy.Request(url, callback=self.parse_product)

        self.logger.info(f"Extracted {product_count} product URLs")

        if product_count == 0 and not self._category_started:
            yield from self._start_category_crawl()

    def _start_category_crawl(self):
        """Start crawling from brand/category pages."""
        self._category_started = True
        self.logger.info(f"Starting category crawl with {len(self.START_CATEGORIES)} entry points")
        for url in self.START_CATEGORIES:
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={'depth': 0},
                dont_filter=True,
            )

    def parse_category(self, response):
        """Extract product links from a brand/category page."""
        if response.status == 403 or b'Just a moment' in response.body[:500]:
            self.logger.warning(f"Category blocked: {response.url}")
            return

        depth = response.meta.get('depth', 0)

        # Product links (Magento 2: .html pages within the domain)
        product_links = set()
        for link in response.css('a::attr(href)').getall():
            full_url = response.urljoin(link)
            if (
                'maxoutil.com/' in full_url
                and full_url.endswith('.html')
                and '/checkout/' not in full_url
                and '/customer/' not in full_url
                and '/catalogsearch/' not in full_url
                and '/catalog/' not in full_url
                and '/media/' not in full_url
                and '/static/' not in full_url
            ):
                path = full_url.replace('https://www.maxoutil.com/', '')
                # Product URLs are flat (no subdirectory)
                if '/' not in path:
                    product_links.add(full_url)

        self.logger.info(f"Category {response.url}: {len(product_links)} product links")
        for url in product_links:
            yield scrapy.Request(url, callback=self.parse_product)

        # Pagination (Magento 2 uses ?p=2, ?p=3)
        next_page = response.css('a[rel="next"]::attr(href)').get()
        if not next_page:
            next_page = response.css(
                'li.pages-item-next a::attr(href), '
                'a.action.next::attr(href), '
                'a[title="Suivant"]::attr(href), '
                'a[title="Page suivante"]::attr(href)'
            ).get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_category,
                                  meta={'depth': depth})

        # Subcategories (max depth 2)
        if depth < 2:
            for link in response.css('a::attr(href)').getall():
                full_url = response.urljoin(link)
                if (
                    'maxoutil.com/' in full_url
                    and not full_url.endswith('.html')
                    and '/checkout/' not in full_url
                    and '/customer/' not in full_url
                    and '?' not in full_url
                    and '#' not in full_url
                    and full_url.rstrip('/') != response.url.rstrip('/')
                ):
                    yield scrapy.Request(
                        full_url,
                        callback=self.parse_category,
                        meta={'depth': depth + 1},
                    )

    def parse_product(self, response):
        """Extract product data from JSON-LD."""
        if response.status == 403 or b'Just a moment' in response.body[:500]:
            self.logger.warning(f"Product blocked: {response.url}")
            return

        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()

        # First pass: BreadcrumbList for category
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

        # Second pass: Product data
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

                # Price
                offers = data.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get('price')
                if not price:
                    continue
                price = float(price)

                # Brand
                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                # SKU
                sku = data.get('sku', '')

                # gtin8 on this site contains internal SKU, NOT real EAN
                # So we don't use it as EAN
                # Try gtin13 just in case they add it later
                ean = data.get('gtin13') or data.get('gtin') or ''

                # MPN
                mpn = data.get('mpn', '')

                # Image
                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                # Description
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

        # Fallback: meta tags
        self._parse_product_fallback(response, category)

    def _parse_product_fallback(self, response, category):
        """Fallback extraction from meta tags and DOM."""
        name = (
            response.css('meta[property="og:title"]::attr(content)').get()
            or response.css('h1.page-title span::text, h1::text').get()
        )
        if not name:
            return
        name = name.strip()

        price_str = (
            response.css('meta[property="product:price:amount"]::attr(content)').get()
            or response.css('span[data-price-type="finalPrice"]::attr(data-price-amount)').get()
            or response.css('.price-wrapper::attr(data-price-amount)').get()
        )
        price = self.parse_price(price_str)
        if not price:
            return

        image = response.css('meta[property="og:image"]::attr(content)').get()

        brand = response.css('meta[property="product:brand"]::attr(content)').get()

        sku = response.css(
            'div[itemprop="sku"]::text, '
            '.product.attribute.sku .value::text'
        ).get()

        desc = response.css('meta[property="og:description"]::attr(content)').get()
        if desc:
            desc = desc[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku.strip() if sku else None,
            manufacturer=brand or None,
            price=price,
            image_url=image or None,
            description=desc or None,
            category_path=category or None,
        )
