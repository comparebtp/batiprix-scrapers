"""Spider for Distriartisan - distriartisan.fr

Strategy:
1. Try sitemaps from robots.txt (/media/sitemap/ paths) with browser-like headers.
2. If sitemaps return 403/blocked, fall back to crawling category pages.
3. Parse product pages via JSON-LD (Magento 2 structured data).

The site uses a WAF from group-dis.com that blocks bots aggressively.
We use realistic browser headers and moderate rate limiting to avoid blocks.
"""
import json
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class DistriartisanSpider(BaseBTPSpider):
    name = 'distriartisan'
    store_chain = 'distriartisan'
    allowed_domains = ['distriartisan.fr']

    # Sitemaps declared in robots.txt (as of 2026-03-21)
    SITEMAPS = [
        'https://www.distriartisan.fr/media/sitemap/sitemapProduitsRetail_1.xml',
        'https://www.distriartisan.fr/media/sitemap/sitemapProduitsMkp_1.xml',
        'https://www.distriartisan.fr/media/sitemap/sitemapProduitsMkp_2.xml',
        'https://www.distriartisan.fr/media/sitemap/sitemapProduitsMkp_3.xml',
        'https://www.distriartisan.fr/media/sitemap/sitemapCategoriesProduits_1.xml',
    ]

    # BTP-relevant category entry points (discovered from site navigation)
    START_CATEGORIES = [
        # Outillage
        'https://www.distriartisan.fr/outillage/',
        'https://www.distriartisan.fr/outillage/outillage-main/',
        'https://www.distriartisan.fr/outillage/outillage-electroportatif/',
        'https://www.distriartisan.fr/outillage/outillage-specialise/',
        'https://www.distriartisan.fr/outillage/materiel-chantier-et-atelier/',
        'https://www.distriartisan.fr/outillage/outillage-specialise/outillage-de-plomberie',
        'https://www.distriartisan.fr/outillage/outillage-specialise/outils-electricien',
        'https://www.distriartisan.fr/outillage/outillage-specialise/outillage-menuisier',
        # Plomberie et chauffage
        'https://www.distriartisan.fr/plomberie-et-chauffage/',
        'https://www.distriartisan.fr/plomberie-et-chauffage/outillage-plomberie/',
        'https://www.distriartisan.fr/plomberie-et-chauffage/outillage-plomberie/coupe-tube-plomberie',
        # Electricite
        'https://www.distriartisan.fr/electricite/',
        'https://www.distriartisan.fr/electricite/eclairage-professionnel/',
        # Couverture
        'https://www.distriartisan.fr/couverture/',
        # Materiaux de construction
        'https://www.distriartisan.fr/materiaux-de-construction/',
        'https://www.distriartisan.fr/materiaux-de-construction/menuiserie/',
        # Revetement de sols et murs
        'https://www.distriartisan.fr/revetement-de-sols-et-murs/',
        'https://www.distriartisan.fr/revetement-de-sols-et-murs/peinture-interieure',
        'https://www.distriartisan.fr/revetement-de-sols-et-murs/carrelage-faience-beton-cire-revetement-decoratif/',
        # Salle de bain
        'https://www.distriartisan.fr/salle-de-bain-wc-cuisine/',
        'https://www.distriartisan.fr/salle-de-bain-wc-cuisine/meuble-salle-de-bain',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.0,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,  # We respect robots.txt manually; the WAF blocks the robots.txt fetch itself
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

    def start_requests(self):
        """Try sitemaps first; if they all fail, fall back to category crawling."""
        self._sitemap_failures = 0
        self._sitemap_total = len(self.SITEMAPS)
        self._category_started = False

        for url in self.SITEMAPS:
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap,
                errback=self.sitemap_failed,
                dont_filter=True,
                meta={'sitemap': True},
            )

    def sitemap_failed(self, failure):
        """Track sitemap failures; start category crawl if all sitemaps failed."""
        self._sitemap_failures += 1
        self.logger.warning(
            f"Sitemap failed ({self._sitemap_failures}/{self._sitemap_total}): "
            f"{failure.request.url} - {failure.value}"
        )
        if self._sitemap_failures >= self._sitemap_total and not self._category_started:
            self.logger.info("All sitemaps failed, falling back to category crawl")
            yield from self._start_category_crawl()

    def parse_sitemap(self, response):
        """Parse sitemap XML and extract product URLs."""
        # Check if we got blocked (403, redirect to homepage, or HTML error page)
        content_type = response.headers.get('Content-Type', b'').decode('utf-8', errors='ignore')
        if response.status == 403 or 'text/html' in content_type or b'Request blocked' in response.body[:500]:
            self._sitemap_failures += 1
            self.logger.warning(
                f"Sitemap blocked ({self._sitemap_failures}/{self._sitemap_total}): "
                f"{response.url} (status={response.status})"
            )
            if self._sitemap_failures >= self._sitemap_total and not self._category_started:
                self.logger.info("All sitemaps blocked, falling back to category crawl")
                yield from self._start_category_crawl()
            return

        # Parse XML sitemap
        response.selector.remove_namespaces()
        urls = response.xpath('//url/loc/text()').getall()
        self.logger.info(f"Found {len(urls)} URLs in sitemap {response.url}")

        product_count = 0
        for url in urls:
            # Product pages end with .html on this Magento 2 site
            if url.endswith('.html'):
                product_count += 1
                yield scrapy.Request(url, callback=self.parse_product)

        self.logger.info(f"Extracted {product_count} product URLs from {response.url}")

        # If the categories sitemap was loaded, also extract category URLs
        if 'Categorie' in response.url:
            for url in urls:
                if not url.endswith('.html') and url != 'https://www.distriartisan.fr/':
                    yield scrapy.Request(url, callback=self.parse_category,
                                         meta={'depth': 0})

    def _start_category_crawl(self):
        """Start crawling from known category entry points."""
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
        """Extract product links and subcategories from a category page."""
        # Skip blocked responses
        if response.status == 403 or b'Request blocked' in response.body[:500]:
            self.logger.warning(f"Category page blocked: {response.url}")
            return

        depth = response.meta.get('depth', 0)

        # Extract product links (Magento 2 product URLs end with .html)
        product_links = set()
        for link in response.css('a::attr(href)').getall():
            if link.endswith('.html') and '/blog/' not in link and '/page/' not in link:
                product_links.add(response.urljoin(link))

        self.logger.info(f"Category {response.url}: found {len(product_links)} product links")

        for url in product_links:
            yield scrapy.Request(url, callback=self.parse_product)

        # Extract subcategory links (max depth 3 to avoid infinite crawl)
        if depth < 3:
            subcategory_links = set()
            for link in response.css('a::attr(href)').getall():
                full_url = response.urljoin(link)
                # Category URLs: no .html, within our domain, not blog/page/checkout
                if (
                    'distriartisan.fr/' in full_url
                    and not full_url.endswith('.html')
                    and '/blog/' not in full_url
                    and '/page/' not in full_url
                    and '/checkout/' not in full_url
                    and '/customer/' not in full_url
                    and '/catalogsearch/' not in full_url
                    and '/catalog/' not in full_url
                    and '?' not in full_url
                    and '#' not in full_url
                    and full_url != response.url
                    and full_url.rstrip('/') != response.url.rstrip('/')
                    and full_url.count('/') >= 4  # At least one path segment after domain
                ):
                    subcategory_links.add(full_url)

            for url in subcategory_links:
                yield scrapy.Request(
                    url,
                    callback=self.parse_category,
                    meta={'depth': depth + 1},
                )

        # Pagination: Magento 2 uses ?p=2, ?p=3 etc. Also look for rel="next"
        next_page = response.css('a[rel="next"]::attr(href)').get()
        if not next_page:
            # Look for next page in pagination links
            next_page = response.css(
                'li.pages-item-next a::attr(href), '
                'a.action.next::attr(href), '
                'a[title="Suivant"]::attr(href), '
                'a[title="Page suivante"]::attr(href)'
            ).get()

        if next_page:
            yield response.follow(
                next_page,
                callback=self.parse_category,
                meta={'depth': depth},
            )

    def parse_product(self, response):
        """Extract product data from JSON-LD structured data."""
        # Skip blocked responses
        if response.status == 403 or b'Request blocked' in response.body[:500]:
            self.logger.warning(f"Product page blocked: {response.url}")
            return

        scripts = response.xpath('//script[@type="application/ld+json"]/text()').getall()

        # First pass: find BreadcrumbList for category
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

        # Second pass: find Product
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

        # Fallback: try to extract from HTML meta tags and DOM if no JSON-LD
        self._parse_product_fallback(response, category)

    def _parse_product_fallback(self, response, category):
        """Fallback product parsing from meta tags and DOM when JSON-LD is missing."""
        name = (
            response.css('meta[property="og:title"]::attr(content)').get()
            or response.css('h1.page-title span::text, h1::text').get()
        )
        if not name:
            return

        name = name.strip()

        # Price from meta or DOM
        price_str = (
            response.css('meta[property="product:price:amount"]::attr(content)').get()
            or response.css('span[data-price-type="finalPrice"]::attr(data-price-amount)').get()
            or response.css('.price-wrapper::attr(data-price-amount)').get()
        )
        if not price_str:
            price_str = response.css(
                'span.price::text, .product-info-price .price::text'
            ).get()

        price = self.parse_price(price_str)
        if not price:
            return

        image = (
            response.css('meta[property="og:image"]::attr(content)').get()
            or response.css('.product.media img::attr(src)').get()
        )

        sku = response.css('div[itemprop="sku"]::text, .product.attribute.sku .value::text').get()

        desc = response.css('meta[property="og:description"]::attr(content)').get()
        if desc:
            desc = desc[:500]

        yield self.make_item(
            product_name=name,
            product_url=response.url,
            sku=sku.strip() if sku else None,
            price=price,
            image_url=image or None,
            description=desc or None,
            category_path=category or None,
        )
