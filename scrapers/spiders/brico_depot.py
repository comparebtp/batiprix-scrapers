"""Spider for Brico Dépôt - bricodepot.fr

Strategy: HTTP-only (no Playwright), sitemap-based.
1. Fetch product sitemaps (5 files, ~22,000 products total)
2. Fetch each product page in plain HTTP
3. Extract structured data from JSON-LD / inline JSON in HTML
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class BricoDepotSpider(BaseBTPSpider):
    name = 'brico_depot'
    store_chain = 'brico_depot'
    allowed_domains = ['bricodepot.fr']

    # Store config — configurable via env vars or scrapy -a store_id=1773 -a store_path=toulon
    STORE_ID = None
    STORE_PATH = None

    def __init__(self, store_id=None, store_path=None, shard=None, total_shards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import os
        self.STORE_ID = store_id or os.environ.get('BD_STORE_ID', '1944')
        self.STORE_PATH = store_path or os.environ.get('BD_STORE_PATH', 'nice-lingostiere')
        self.shard = int(shard) if shard is not None else None
        self.total_shards = int(total_shards) if total_shards is not None else None
        # Update cookie header with selected store
        self.custom_settings = dict(self.custom_settings)
        headers = dict(self.custom_settings.get('DEFAULT_REQUEST_HEADERS', {}))
        headers['Cookie'] = f'USER_LAST_VISITED_STORE_ID={self.STORE_ID}; USER_LAST_VISITED_STORE_PATH=/{self.STORE_PATH}; USER_LAST_VISITED_SITE={self.STORE_ID}'
        self.custom_settings['DEFAULT_REQUEST_HEADERS'] = headers

    custom_settings = {
        'DOWNLOAD_DELAY': 1.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'ROBOTSTXT_OBEY': True,
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'COOKIES_ENABLED': True,
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cookie': 'USER_LAST_VISITED_STORE_ID=1944; USER_LAST_VISITED_STORE_PATH=/nice-lingostiere; USER_LAST_VISITED_SITE=1944',
        },
        'DOWNLOAD_TIMEOUT': 60,
        'RETRY_TIMES': 3,
        'RETRY_HTTP_CODES': [403, 429, 500, 502, 503, 504],
    }

    # BTP-relevant keywords to filter products from sitemap
    BTP_KEYWORDS = {
        'outillage', 'outil', 'perceuse', 'visseuse', 'meuleuse', 'scie',
        'tournevis', 'marteau', 'pince', 'cle', 'niveau', 'metre',
        'peinture', 'rouleau', 'pinceau', 'enduit', 'lasure', 'vernis',
        'plomberie', 'robinet', 'tuyau', 'raccord', 'siphon', 'mitigeur',
        'ciment', 'beton', 'mortier', 'parpaing', 'brique', 'agglo',
        'electricite', 'cable', 'gaine', 'prise', 'interrupteur', 'tableau',
        'carrelage', 'faience', 'sol', 'stratifie', 'parquet', 'moquette',
        'isolation', 'isolant', 'laine', 'polystyrene', 'placo',
        'visserie', 'vis', 'boulon', 'cheville', 'fixation', 'ecrou',
        'quincaillerie', 'serrure', 'poignee', 'charniere', 'ferrure',
        'fenetre', 'porte', 'volet', 'menuiserie', 'escalier',
        'chauffage', 'radiateur', 'chaudiere', 'thermostat',
        'sanitaire', 'wc', 'lavabo', 'douche', 'baignoire', 'vasque',
        'eclairage', 'ampoule', 'spot', 'luminaire', 'plafonnier',
        'bois', 'panneau', 'tasseau', 'lambris', 'moulure',
        'toiture', 'gouttiere', 'tuile', 'ardoise', 'couverture',
        'facade', 'crepi', 'ravalement', 'etancheite',
        'jardin', 'cloture', 'grillage', 'terrasse', 'dalle',
        'colle', 'mastic', 'silicone', 'mousse', 'joint',
        'protection', 'gant', 'lunette', 'casque', 'chaussure',
        'echelle', 'escabeau', 'echafaudage', 'brouette',
        'disque', 'foret', 'lame', 'trepan', 'meche', 'abrasif',
        'cutter', 'couteau', 'ciseau', 'spatule', 'truelle',
        'serre-joint', 'etau', 'maillet', 'burin', 'lime',
        'rangement', 'caisse', 'coffret', 'servante', 'etabli',
        'compresseur', 'pompe', 'nettoyeur', 'karcher',
        'soudure', 'poste', 'electrode', 'brasure',
    }

    def start_requests(self):
        # Fetch all 5 product sitemaps; collect URLs for sharding
        self._all_product_urls = []
        self._sitemaps_remaining = 5
        for i in ['', '2', '3', '4', '5']:
            url = f'https://www.bricodepot.fr/productSitemap{i}.xml'
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap,
                headers={'Accept': 'application/xml, text/xml, */*'},
                dont_filter=True,
            )

    def parse_sitemap(self, response):
        """Extract product URLs from sitemap XML, then shard if needed."""
        body = response.text

        # Validate we got actual XML, not a blocked/interstitial page
        if not body or '<urlset' not in body:
            self.logger.error(
                f"Sitemap {response.url} returned non-XML content "
                f"(status={response.status}, length={len(body)}, "
                f"first 200 chars: {body[:200]})"
            )
            self._sitemaps_remaining -= 1
            if self._sitemaps_remaining == 0:
                yield from self._dispatch_product_urls()
            return

        # Extract all product URLs from sitemap
        urls = re.findall(
            r'<loc>(https://www\.bricodepot\.fr/catalogue/[^<]+)</loc>',
            body,
        )
        self.logger.info(
            f"Sitemap {response.url}: {len(urls)} URLs found "
            f"(response size: {len(body)} bytes)"
        )

        if len(urls) == 0:
            # Log more details for debugging on CI
            all_locs = re.findall(r'<loc>([^<]+)</loc>', body)
            self.logger.warning(
                f"No /catalogue/ URLs in sitemap. Total <loc> tags: {len(all_locs)}. "
                f"Sample URLs: {all_locs[:3]}"
            )
        else:
            for url in urls:
                # Extract product slug from URL for keyword filtering
                slug = url.split('/catalogue/')[-1].lower() if '/catalogue/' in url else ''

                # Check if URL matches BTP keywords
                if any(kw in slug for kw in self.BTP_KEYWORDS):
                    # Extract category from URL path
                    parts = slug.strip('/').split('/')
                    cat_name = parts[0].replace('-', ' ').title() if parts else 'Divers'
                    self._all_product_urls.append((url, cat_name))

            self.logger.info(
                f"After filtering: {len(self._all_product_urls)} BTP-relevant products so far"
            )

        self._sitemaps_remaining -= 1
        if self._sitemaps_remaining == 0:
            yield from self._dispatch_product_urls()

    def _dispatch_product_urls(self):
        """Apply sharding and yield product requests."""
        product_urls = self._all_product_urls
        self.logger.info(f"Total BTP-relevant product URLs: {len(product_urls)}")

        # If sharding, only take our slice
        if self.shard is not None and self.total_shards is not None:
            chunk_size = max(1, len(product_urls) // self.total_shards)
            start = self.shard * chunk_size
            end = len(product_urls) if self.shard == self.total_shards - 1 else start + chunk_size
            product_urls = product_urls[start:end]
            self.logger.info(f"Shard {self.shard}/{self.total_shards}: {len(product_urls)} URLs")

        for url, cat_name in product_urls:
            yield scrapy.Request(
                url,
                callback=self.parse_product,
                meta={'category_path': [cat_name]},
                priority=1,
            )

    def parse_product(self, response):
        """Extract product data from product page HTML."""
        # Skip non-200 or blocked responses
        if response.status != 200:
            self.logger.warning(f"Non-200 status {response.status} for {response.url}")
            return

        category_path = response.meta.get('category_path', [])

        # Try JSON-LD first
        json_ld_scripts = response.css('script[type="application/ld+json"]::text').getall()
        for script in json_ld_scripts:
            try:
                data = json.loads(script)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product':
                            data = item
                            break
                if data.get('@type') == 'Product':
                    name = data.get('name', '')
                    sku = data.get('sku', '')
                    brand = data.get('brand', {}).get('name', '') if isinstance(data.get('brand'), dict) else ''
                    image = data.get('image', '')
                    if isinstance(image, list):
                        image = image[0] if image else ''
                    description = data.get('description', '')

                    # EAN from GTIN fields
                    ean = data.get('gtin13') or data.get('gtin') or ''
                    if not ean and data.get('gtin14'):
                        ean = data.get('gtin14', '')[:13]

                    # Manufacturer reference / productID — often contains EAN on Brico Dépôt
                    manufacturer_ref = data.get('mpn') or data.get('productID') or ''

                    # If manufacturer_ref looks like an EAN (13 digits), use it as EAN
                    if not ean and manufacturer_ref and len(manufacturer_ref) == 13 and manufacturer_ref.isdigit():
                        ean = manufacturer_ref
                        manufacturer_ref = ''

                    # Extract specifications from additionalProperty
                    specs = {}
                    for prop in data.get('additionalProperty', []):
                        prop_name = prop.get('name', '').lower()
                        prop_value = prop.get('value', '')
                        if prop_value:
                            specs[prop_name] = str(prop_value)

                    # Also get weight, dimensions from top-level
                    if data.get('weight'):
                        w = data['weight']
                        specs['weight'] = w.get('value', '') + ' ' + w.get('unitText', '') if isinstance(w, dict) else str(w)
                    if data.get('width'):
                        specs['width'] = str(data['width'].get('value', '')) if isinstance(data['width'], dict) else str(data['width'])
                    if data.get('height'):
                        specs['height'] = str(data['height'].get('value', '')) if isinstance(data['height'], dict) else str(data['height'])
                    if data.get('color'):
                        specs['color'] = str(data['color'])
                    if data.get('material'):
                        specs['material'] = str(data['material'])

                    # Price from offers
                    offers = data.get('offers', {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get('price')
                    if price:
                        price = float(price)
                    else:
                        continue

                    yield self.make_item(
                        product_name=name,
                        product_url=response.url,
                        sku=sku,
                        ean=ean or None,
                        manufacturer=brand or None,
                        manufacturer_ref=manufacturer_ref or None,
                        price=price,
                        image_url=image,
                        category_path=category_path,
                        description=description[:500] if description else None,
                        specifications=specs or None,
                    )
                    return
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Fallback: extract from inline JSON/HTML
        # Look for price in various patterns
        price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', response.text)
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', response.text)
        sku_match = re.search(r'"sku"\s*:\s*"([^"]+)"', response.text)

        if price_match and name_match:
            price = float(price_match.group(1))
            name = name_match.group(1)
            sku = sku_match.group(1) if sku_match else ''

            if price > 0 and name:
                yield self.make_item(
                    product_name=name,
                    product_url=response.url,
                    sku=sku,
                    price=price,
                    category_path=category_path,
                )
