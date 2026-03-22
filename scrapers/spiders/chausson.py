"""Spider for Chausson Matériaux - chausson.fr

Strategy:
1. Crawl /categories to discover all category page URLs (2000+ categories).
2. For each category page, extract the categoryFilter UUID and totalPages.
3. Use the internal API /api/catalog/search-products to paginate and collect
   product URLs from the HTML fragments returned.
4. Parse each product page via JSON-LD (Product schema with name, sku, gtin13,
   brand, price, availability).

The site has 40,000+ products.  Prices are publicly visible (HT by default)
and can be localized per agency.  No sitemap is available.

Note: SSL may require verification to be disabled on some systems.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class ChaussonSpider(BaseBTPSpider):
    name = 'chausson'
    store_chain = 'chausson'
    allowed_domains = ['chausson.fr', 'www.chausson.fr']

    custom_settings = {
        'DOWNLOAD_DELAY': 2.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        },
        'RETRY_TIMES': 2,
        'RETRY_HTTP_CODES': [403, 429, 500, 502, 503],
    }

    # Top-level category pages as fallback entry points
    FALLBACK_CATEGORIES = [
        'https://www.chausson.fr/Materiaux/c/20000',
        'https://www.chausson.fr/Quincaillerie/c/2005',
        'https://www.chausson.fr/Quincaillerie/c/2003',
        'https://www.chausson.fr/Quincaillerie/c/20033',
        'https://www.chausson.fr/Quincaillerie/c/20034',
    ]

    PRODUCT_URL_RE = re.compile(r'-p-\d+')

    def __init__(self, shard=None, total_shards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shard = int(shard) if shard is not None else None
        self.total_shards = int(total_shards) if total_shards is not None else None

    def start_requests(self):
        """Start by fetching the categories index page."""
        yield scrapy.Request(
            'https://www.chausson.fr/categories',
            callback=self.parse_categories_index,
            errback=self._categories_index_failed,
            dont_filter=True,
        )

    def _categories_index_failed(self, failure):
        """Fallback to hardcoded category entry points."""
        self.logger.warning(
            f"Categories index failed: {failure.value}, "
            f"falling back to {len(self.FALLBACK_CATEGORIES)} entry points"
        )
        for url in self.FALLBACK_CATEGORIES:
            yield scrapy.Request(url, callback=self.parse_category_page)

    def parse_categories_index(self, response):
        """Extract all category URLs from the /categories page."""
        cat_urls = set()
        for href in response.css('a::attr(href)').getall():
            if '/c/' in href and not href.startswith(('http://', 'https://')):
                cat_urls.add(response.urljoin(href))
            elif '/c/' in href and 'chausson.fr' in href:
                cat_urls.add(href)

        self.logger.info(f"Found {len(cat_urls)} category URLs from /categories")

        if not cat_urls:
            self.logger.warning("No category URLs found, using fallback")
            for url in self.FALLBACK_CATEGORIES:
                yield scrapy.Request(url, callback=self.parse_category_page)
            return

        cat_urls = sorted(cat_urls)

        # Apply sharding at category level
        if self.shard is not None and self.total_shards is not None:
            chunk_size = max(1, len(cat_urls) // self.total_shards)
            start = self.shard * chunk_size
            end = len(cat_urls) if self.shard == self.total_shards - 1 else start + chunk_size
            cat_urls = cat_urls[start:end]
            self.logger.info(
                f"Shard {self.shard}/{self.total_shards}: "
                f"processing {len(cat_urls)} categories"
            )

        for url in cat_urls:
            yield scrapy.Request(url, callback=self.parse_category_page)

    def parse_category_page(self, response):
        """Parse a category page: extract products and discover pagination via API."""
        if response.status in (403, 404):
            return

        # Extract product links from the initial HTML
        for href in response.css('a::attr(href)').getall():
            if self.PRODUCT_URL_RE.search(href):
                yield response.follow(href, callback=self.parse_product)

        # Extract subcategory links (for categories that list children, not products)
        for href in response.css('a::attr(href)').getall():
            full_url = response.urljoin(href)
            if (
                '/c/' in href
                and 'chausson.fr' in full_url
                and full_url != response.url
                and full_url.rstrip('/') != response.url.rstrip('/')
            ):
                yield scrapy.Request(full_url, callback=self.parse_category_page)

        # Check for pagination via the API
        # Extract categoryFilter UUID and totalPages from inline JS
        body_text = response.text
        cat_filter_match = re.search(
            r"categoryFilter:\s*'([0-9a-f-]{36})'", body_text
        )
        total_pages_match = re.search(
            r'totalPages:\s*(\d+)', body_text
        )

        if cat_filter_match and total_pages_match:
            cat_filter = cat_filter_match.group(1)
            total_pages = int(total_pages_match.group(1))

            if total_pages > 1:
                self.logger.info(
                    f"Category {response.url}: {total_pages} pages, "
                    f"loading pages 2-{total_pages} via API"
                )
                for page in range(2, total_pages + 1):
                    api_url = (
                        f'https://www.chausson.fr/api/catalog/search-products?'
                        f'categoryFilter={cat_filter}'
                        f'&pageIndex={page}'
                        f'&pageSize=20'
                        f'&searchInAllAgencies=true'
                    )
                    yield scrapy.Request(
                        api_url,
                        callback=self.parse_api_page,
                        headers={
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'text/html',
                        },
                    )

    def parse_api_page(self, response):
        """Parse an API search results page (HTML fragment) for product links."""
        if response.status in (403, 404):
            return

        for href in response.css('a::attr(href)').getall():
            if self.PRODUCT_URL_RE.search(href):
                yield response.follow(href, callback=self.parse_product)

    def parse_product(self, response):
        """Extract product data from JSON-LD structured data."""
        if response.status in (403, 404):
            return

        scripts = response.xpath(
            '//script[@type="application/ld+json"]/text()'
        ).getall()

        # Look for BreadcrumbList for category path
        category = []
        for script in scripts:
            try:
                data = json.loads(script)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    for item in data.get('itemListElement', []):
                        name = item.get('name', '').strip()
                        if name:
                            category.append(name)
            except (json.JSONDecodeError, ValueError):
                pass

        # Look for Product JSON-LD
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

                # EAN
                ean = data.get('gtin13') or data.get('gtin') or ''

                # Brand
                brand = data.get('brand', {})
                if isinstance(brand, dict):
                    brand = brand.get('name', '')

                # SKU
                sku = data.get('sku', '')

                # MPN
                mpn = data.get('mpn', '')

                # Image
                image = data.get('image', '')
                if isinstance(image, list):
                    image = image[0] if image else ''
                if isinstance(image, dict):
                    image = image.get('url', '')

                # Description
                desc = (
                    data.get('description', '')[:500]
                    if data.get('description')
                    else ''
                )

                # In stock
                availability = offers.get('availability', '')
                in_stock = availability.endswith('InStock')

                # Category from JSON-LD "category" field (URLs) as fallback
                if not category:
                    cat_data = data.get('category', [])
                    if isinstance(cat_data, list):
                        for cat_url in cat_data:
                            if isinstance(cat_url, str):
                                # Extract category name from URL slug
                                slug = cat_url.rstrip('/').split('/')[-1]
                                slug = re.sub(r'-c-.*$', '', slug)
                                category.append(
                                    slug.replace('-', ' ').title()
                                )

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
                    in_stock=in_stock,
                )
                return

            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        # Fallback: parse from HTML if no JSON-LD
        self._parse_product_fallback(response, category)

    def _parse_product_fallback(self, response, category):
        """Fallback product parsing from HTML when JSON-LD is missing."""
        name = response.css(
            'h1.product-title::text, '
            'h1::text, '
            'meta[property="og:title"]::attr(content)'
        ).get()
        if not name:
            return
        name = name.strip()

        # Price from the page
        price_str = response.css(
            'price::text, '
            '.prix-principal price::text, '
            '.product-price price::text, '
            'meta[property="product:price:amount"]::attr(content)'
        ).get()
        price = self.parse_price(price_str)
        if not price:
            return

        # SKU
        sku = response.css(
            '.product-reference::text, '
            '[class*="reference"]::text'
        ).get()
        if sku:
            sku = re.sub(r'^Code\s*:\s*', '', sku).strip()

        # Image
        image = response.css(
            'meta[property="og:image"]::attr(content), '
            '.product-image img::attr(src), '
            '.product-image img::attr(data-src)'
        ).get()

        # Description
        desc = response.css(
            'meta[property="og:description"]::attr(content)'
        ).get()
        if desc:
            desc = desc[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku or None,
            price=price,
            image_url=image or None,
            description=desc or None,
            category_path=category or None,
        )
