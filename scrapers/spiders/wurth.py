"""Spider for Würth France - eshop.wurth.fr

Strategy (hybrid search + product pages):
1. Use the search results page for each BTP term to find products directly.
   The search page shows product cards with names, prices (HT), article numbers,
   images, and links to .sku product pages.
2. Also use the Suggest API to discover product group pages, then follow
   .sku links from those pages.
3. On individual .sku product pages, extract JSON-LD structured data
   (ProductGroup with sku, gtin13, brand) plus page HTML for prices.

Note: Prices require login for many products ("Prix sur demande").
The search results page sometimes shows prices ("XX € H.T.") for popular items.
"""
import json
import re
import scrapy
from scrapers.spiders.base import BaseBTPSpider


class WurthSpider(BaseBTPSpider):
    name = 'wurth'
    store_chain = 'wurth'
    allowed_domains = ['eshop.wurth.fr']

    BASE_URL = 'https://eshop.wurth.fr'
    SEARCH_URL = 'https://eshop.wurth.fr/Recherche/resultat-recherche.htm'
    SUGGEST_URL = (
        'https://eshop.wurth.fr/is-bin/INTERSHOP.enfinity/WFS/'
        '3107-B1-Site/fr_FR/-/EUR/ViewParametricSearch-Suggest'
    )

    # BTP search terms to cover the catalog
    SEARCH_TERMS = [
        # Outillage a main
        'tournevis', 'pince', 'cle', 'marteau', 'niveau', 'metre',
        'scie', 'cisaille', 'lime', 'burin', 'spatule', 'truelle',
        # Outillage electroportatif
        'perceuse', 'visseuse', 'meuleuse', 'perforateur', 'scie sauteuse',
        'ponceuse', 'rabot', 'defonceuse', 'decoupeur',
        # Visserie fixation
        'vis', 'boulon', 'ecrou', 'cheville', 'rivet', 'agrafe',
        'clou', 'rondelle', 'tige filetee',
        # Produits chimiques
        'colle', 'mastic', 'silicone', 'mousse polyurethane', 'degrippant',
        'lubrifiant', 'nettoyant frein', 'scellement chimique',
        # Electricite
        'cable', 'gaine', 'collier', 'attache cable', 'domino', 'connecteur',
        # Mesure
        'metre laser', 'niveau laser', 'equerre', 'compas', 'rapporteur',
        # EPI
        'gant', 'lunette protection', 'casque', 'chaussure securite',
        'gilet', 'bouchon oreille',
        # Abrasifs
        'disque', 'foret', 'lame scie', 'trepan', 'meche',
        # Plomberie
        'raccord', 'tuyau', 'collier serrage', 'robinet', 'joint',
        # Construction
        'echafaudage', 'echelle', 'escabeau', 'brouette', 'serre joint',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
        'ROBOTSTXT_OBEY': False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_skus = set()           # deduplicate by SKU/article number
        self.seen_group_ids = set()      # deduplicate product group pages

    def start_requests(self):
        # --- Phase 1: Search results pages (direct product extraction) ---
        for term in self.SEARCH_TERMS:
            yield scrapy.Request(
                f'{self.SEARCH_URL}?SearchTerm={term}',
                callback=self.parse_search_results,
                meta={'search_term': term},
            )

        # --- Phase 2: Suggest API for product group discovery ---
        for term in self.SEARCH_TERMS:
            yield scrapy.Request(
                f'{self.SUGGEST_URL}?SearchTerm={term}',
                callback=self.parse_suggest,
                meta={'search_term': term},
                headers={'Accept': 'application/json'},
            )

    # ------------------------------------------------------------------
    # Phase 1: Search results page -> extract product cards directly
    # ------------------------------------------------------------------

    def parse_search_results(self, response):
        """Parse search results page for product cards.

        Product cards use .produit containers inside .swiper-slide elements.
        Each card has: .titre (name), .ref (article number), price text,
        image, and a link to the .sku product page.
        """
        search_term = response.meta.get('search_term', '')

        # Find all product containers - try multiple selectors
        products = response.css('.produit')
        if not products:
            products = response.css('.swiper-slide')

        self.logger.info(
            f"Search '{search_term}': found {len(products)} product cards"
        )

        items_from_page = 0
        for card in products:
            item = self._extract_from_card(card, response, search_term)
            if item:
                items_from_page += 1
                yield item

        # Also find all .sku links on the page and follow them for
        # more detailed data (JSON-LD with EAN, etc.)
        sku_links = response.css('a[href*=".sku/"]::attr(href)').getall()
        sku_links = list(set(sku_links))

        for href in sku_links:
            # Extract SKU from URL to check dedup
            sku_match = re.search(r'/([^/]+)\.sku/', href)
            if not sku_match:
                continue
            sku = sku_match.group(1).replace('%20', ' ')
            normalized = sku.replace(' ', '')

            full_url = response.urljoin(href)
            yield scrapy.Request(
                full_url,
                callback=self.parse_product_page,
                meta={
                    'search_term': search_term,
                    'sku_hint': sku,
                },
                errback=self.handle_error,
                dont_filter=False,
            )

        self.logger.info(
            f"Search '{search_term}': {items_from_page} items extracted, "
            f"{len(sku_links)} .sku links to follow"
        )

    def _extract_from_card(self, card, response, search_term):
        """Extract product data from a search result card element."""
        # Product name from .titre or a[title]
        name = card.css('.titre::text').get('').strip()
        if not name:
            name = card.css('.titre a::text').get('').strip()
        if not name:
            name = card.css('a[title]::attr(title)').get('').strip()
        if not name:
            # Try any link text
            name = card.css('a::text').get('').strip()
        if not name:
            return None

        # Article number from .ref
        ref_text = card.css('.ref::text').get('')
        if not ref_text:
            ref_text = card.css('.ref *::text').get('')
        ref = ''
        if ref_text:
            # Extract digits from "Art. N° 071566 295" or "096513 023"
            ref_match = re.search(r'(\d[\d\s]+\d)', ref_text)
            if ref_match:
                ref = ref_match.group(1).strip()

        # Normalize SKU for dedup
        normalized = ref.replace(' ', '') if ref else ''
        if not normalized:
            # Try extracting from product URL
            href = card.css('a[href*=".sku/"]::attr(href)').get('')
            if href:
                sku_match = re.search(r'/([^/]+)\.sku/', href)
                if sku_match:
                    ref = sku_match.group(1).replace('%20', ' ')
                    normalized = ref.replace(' ', '')

        if not normalized:
            return None

        if normalized in self.seen_skus:
            return None
        self.seen_skus.add(normalized)

        # Product URL
        product_url = card.css('a[href*=".sku/"]::attr(href)').get('')
        if not product_url:
            product_url = card.css('a::attr(href)').get('')
        if product_url:
            product_url = response.urljoin(product_url)

        # Price - look for HT price pattern
        card_text = ' '.join(card.css('::text').getall())
        price = self._parse_ht_price(card_text)

        # Image
        image = card.css('img::attr(src)').get('')
        if not image:
            image = card.css('img::attr(data-src)').get('')
        if image:
            image = response.urljoin(image)

        return self.make_item(
            product_name=name,
            product_url=product_url or response.url,
            sku=ref,
            manufacturer_ref=ref,
            manufacturer='Würth',
            price=price,
            unit_label='€ HT' if price else None,
            image_url=image or '',
            category_path=[search_term.title()],
        )

    # ------------------------------------------------------------------
    # Phase 2: Suggest API -> product group pages -> .sku pages
    # ------------------------------------------------------------------

    def parse_suggest(self, response):
        """Parse the JSON suggest API response to discover product groups."""
        search_term = response.meta.get('search_term', '')
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning(f"Suggest API: invalid JSON for '{search_term}'")
            return

        products = data.get('compressedProducts', [])
        self.logger.info(
            f"Suggest '{search_term}': {len(products)} product groups "
            f"(total: {data.get('numberOfFoundProducts', '?')})"
        )

        for item in products:
            label = item.get('label', '').strip()
            value = item.get('value', '')
            image = item.get('image', '')

            # Extract product group ID: "nameExact:31076013030305:nameExact tournevis"
            id_match = re.search(r'nameExact:(\d+)', value)
            if not id_match:
                continue
            group_id = id_match.group(1)

            if group_id in self.seen_group_ids:
                continue
            self.seen_group_ids.add(group_id)

            # Build category-style URL to the product group page
            slug = re.sub(r'[^a-zA-Z0-9]+', '-', label).strip('-')
            group_url = (
                f'{self.BASE_URL}/Categories-produits/{slug}/'
                f'{group_id}.cyid/3107.cgid/fr/FR/EUR/'
            )

            # Resolve image URL
            if image and not image.startswith('http'):
                image = response.urljoin(image)

            yield scrapy.Request(
                group_url,
                callback=self.parse_product_group,
                meta={
                    'search_term': search_term,
                    'group_name': label,
                    'group_image': image,
                    'group_id': group_id,
                },
                errback=self.handle_error,
            )

    def parse_product_group(self, response):
        """Parse a product group page. Extract .sku links and follow them."""
        search_term = response.meta.get('search_term', '')
        group_name = response.meta.get('group_name', '')
        group_image = response.meta.get('group_image', '')

        # Collect all .sku links from the page
        sku_links = set()

        # From HTML links
        for href in response.css('a[href*=".sku/"]::attr(href)').getall():
            sku_links.add(response.urljoin(href))

        # From embedded JavaScript (itemUrl, product URLs)
        body_text = response.text
        for match in re.findall(r'"(?:itemUrl|url)"\s*:\s*"([^"]*\.sku/[^"]*)"', body_text):
            sku_links.add(response.urljoin(match))

        # From JSON-LD hasVariant URLs
        for script_text in response.css('script[type="application/ld+json"]::text').getall():
            try:
                ld_data = json.loads(script_text)
            except (json.JSONDecodeError, ValueError):
                continue
            if ld_data.get('@type') == 'ProductGroup':
                for variant in ld_data.get('hasVariant', []):
                    url = variant.get('url', '')
                    if '.sku/' in url:
                        sku_links.add(url)

        # From skusOfProductsToDisplayWithoutFilters JS array
        sku_ids = re.findall(
            r'"skusOfProductsToDisplayWithoutFilters"\s*:\s*\[([^\]]+)\]',
            body_text
        )
        for match in sku_ids:
            for sku_id in re.findall(r'"([^"]+)"', match):
                sku_url = f'{self.BASE_URL}/{sku_id}.sku/fr/FR/EUR/'
                sku_links.add(sku_url)

        self.logger.info(
            f"Product group '{group_name}': {len(sku_links)} .sku links found"
        )

        for link in sku_links:
            yield scrapy.Request(
                link,
                callback=self.parse_product_page,
                meta={
                    'search_term': search_term,
                    'group_name': group_name,
                    'group_image': group_image,
                },
                errback=self.handle_error,
            )

        # If no .sku links found, try to extract directly from JSON-LD
        if not sku_links:
            yield from self._extract_from_group_jsonld(
                response, search_term, group_name, group_image
            )

    # ------------------------------------------------------------------
    # Product detail page (.sku URL) -> final item extraction
    # ------------------------------------------------------------------

    def parse_product_page(self, response):
        """Parse an individual .sku product page.

        Extracts data from:
        1. JSON-LD (ProductGroup with sku, gtin13, brand at top level)
        2. Page HTML (Art. N°, prices, images)
        3. Embedded JS (modelDetailConfig, dataLayer)
        """
        search_term = response.meta.get('search_term', '')
        group_name = response.meta.get('group_name', '')
        group_image = response.meta.get('group_image', '')

        # --- Try JSON-LD first ---
        extracted = False
        for script_text in response.css('script[type="application/ld+json"]::text').getall():
            try:
                ld_data = json.loads(script_text)
            except (json.JSONDecodeError, ValueError):
                continue

            ld_type = ld_data.get('@type', '')

            if ld_type == 'ProductGroup':
                # On .sku pages, the ProductGroup often has sku and gtin13
                # at the top level (not inside hasVariant)
                sku = ld_data.get('sku', '')
                name = ld_data.get('name', '')
                ean = ld_data.get('gtin13', '')
                description = ld_data.get('description', '')
                brand = ''
                brand_obj = ld_data.get('brand', {})
                if isinstance(brand_obj, dict):
                    brand = brand_obj.get('name', '')

                # Also check hasVariant for additional data
                variants = ld_data.get('hasVariant', [])

                # Image from JSON-LD or page (needed for both main product and variants)
                image = self._get_image(ld_data)
                if not image:
                    image = group_image or ''
                if not image:
                    image = response.css(
                        'img[src*="media.witglobal.net"]::attr(src)'
                    ).get('')

                if sku:
                    normalized = sku.replace(' ', '')
                    if normalized not in self.seen_skus:
                        self.seen_skus.add(normalized)

                        # Try to get price from page
                        price = self._extract_ht_price(response)

                        yield self.make_item(
                            product_name=name,
                            product_url=response.url,
                            sku=sku,
                            ean=ean or None,
                            manufacturer_ref=sku,
                            manufacturer=brand or 'Würth',
                            price=price,
                            unit_label='€ HT' if price else None,
                            image_url=image or '',
                            category_path=[search_term.title()] if search_term else [],
                            description=description or None,
                        )
                        extracted = True

                # Process variants that have their own SKU
                for variant in variants:
                    v_sku = variant.get('sku', '')
                    if not v_sku:
                        # Try to extract SKU from variant URL
                        v_url = variant.get('url', '')
                        if v_url:
                            m = re.search(r'/([^/]+)\.sku/', v_url)
                            if m:
                                v_sku = m.group(1)
                    if not v_sku:
                        continue

                    v_normalized = v_sku.replace(' ', '').replace('%20', '')
                    if v_normalized in self.seen_skus:
                        continue
                    self.seen_skus.add(v_normalized)

                    v_name = variant.get('name', name)
                    v_ean = variant.get('gtin13', '')
                    v_url = variant.get('url', response.url)
                    v_image = self._get_image(variant) or image

                    # If variant has its own URL different from current page,
                    # follow it to get full details
                    if v_url and v_url != response.url and '.sku/' in v_url:
                        yield scrapy.Request(
                            v_url,
                            callback=self.parse_product_page,
                            meta={
                                'search_term': search_term,
                                'group_name': group_name,
                                'group_image': group_image,
                            },
                            errback=self.handle_error,
                        )
                    else:
                        yield self.make_item(
                            product_name=v_name,
                            product_url=v_url or response.url,
                            sku=v_sku,
                            ean=v_ean or None,
                            manufacturer_ref=v_sku,
                            manufacturer=brand or 'Würth',
                            image_url=v_image or '',
                            category_path=[search_term.title()] if search_term else [],
                            description=description or None,
                        )
                        extracted = True

            elif ld_type == 'Product':
                sku = ld_data.get('sku', '')
                if not sku:
                    continue
                normalized = sku.replace(' ', '')
                if normalized in self.seen_skus:
                    continue
                self.seen_skus.add(normalized)

                name = ld_data.get('name', '')
                ean = ld_data.get('gtin13', '')
                image = self._get_image(ld_data)
                price = self._extract_price_from_offers(ld_data)
                if not price:
                    price = self._extract_ht_price(response)

                yield self.make_item(
                    product_name=name,
                    product_url=ld_data.get('url', response.url),
                    sku=sku,
                    ean=ean or None,
                    manufacturer_ref=sku,
                    manufacturer='Würth',
                    price=price,
                    unit_label='€ HT' if price else None,
                    image_url=image or '',
                    category_path=[search_term.title()] if search_term else [],
                    description=ld_data.get('description', '') or None,
                )
                extracted = True

        # --- Fallback: extract from page HTML if no JSON-LD match ---
        if not extracted:
            yield from self._fallback_html_extract(response, search_term, group_image)

    # ------------------------------------------------------------------
    # Fallback extractors
    # ------------------------------------------------------------------

    def _extract_from_group_jsonld(self, response, search_term, group_name, group_image):
        """Extract from JSON-LD on a product group page that has no .sku links."""
        for script_text in response.css('script[type="application/ld+json"]::text').getall():
            try:
                ld_data = json.loads(script_text)
            except (json.JSONDecodeError, ValueError):
                continue

            if ld_data.get('@type') != 'ProductGroup':
                continue

            sku = ld_data.get('sku', '')
            name = ld_data.get('name', group_name)
            ean = ld_data.get('gtin13', '')

            if sku:
                normalized = sku.replace(' ', '')
                if normalized not in self.seen_skus:
                    self.seen_skus.add(normalized)
                    yield self.make_item(
                        product_name=name,
                        product_url=response.url,
                        sku=sku,
                        ean=ean or None,
                        manufacturer_ref=sku,
                        manufacturer='Würth',
                        image_url=group_image or self._get_image(ld_data) or '',
                        category_path=[search_term.title()] if search_term else [],
                        description=ld_data.get('description', '') or None,
                    )

    def _fallback_html_extract(self, response, search_term, group_image=''):
        """Fallback: extract product data from page HTML when JSON-LD is missing."""
        # Product name from h1
        title = response.css('h1::text').get('').strip()
        if not title:
            title = ' '.join(response.css('h1 *::text').getall()).strip()
        if not title:
            return

        # Article number from page text
        all_text = ' '.join(response.css('::text').getall())
        ref_match = re.search(r'Art\.\s*N[°o]\s*([\d\s]+\d)', all_text)
        ref = ref_match.group(1).strip() if ref_match else ''

        if not ref:
            # Try extracting from URL
            url_match = re.search(r'/([^/]+)\.sku/', response.url)
            if url_match:
                ref = url_match.group(1).replace('%20', ' ')

        if not ref:
            return

        normalized = ref.replace(' ', '')
        if normalized in self.seen_skus:
            return
        self.seen_skus.add(normalized)

        # Price
        price = self._extract_ht_price(response)

        # Image
        image = response.css(
            'img[src*="media.witglobal.net"]::attr(src)'
        ).get(group_image or '')

        # EAN from page text
        ean_match = re.search(r'(?:EAN|GTIN)\s*:?\s*(\d{13})', all_text)
        ean = ean_match.group(1) if ean_match else ''

        yield self.make_item(
            product_name=title,
            product_url=response.url,
            sku=ref,
            ean=ean or None,
            manufacturer_ref=ref,
            manufacturer='Würth',
            price=price,
            unit_label='€ HT' if price else None,
            image_url=image or '',
            category_path=[search_term.title()] if search_term else [],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ht_price(text):
        """Parse HT price from a text string.

        Looks for patterns like '89 € H.T.' or '12,50 € H.T. l'unité'
        or 'à partir de 7 € H.T.'
        """
        # Pattern: number followed by € H.T.
        match = re.search(
            r'(\d+(?:[.,]\d+)?)\s*€\s*H\.?T\.?', text
        )
        if match:
            return float(match.group(1).replace(',', '.'))
        return None

    def _extract_ht_price(self, response):
        """Extract HT price from the full page text."""
        all_text = ' '.join(response.css('::text').getall())
        return self._parse_ht_price(all_text)

    @staticmethod
    def _get_image(ld_obj):
        """Extract image URL from a JSON-LD object."""
        img = ld_obj.get('image', '')
        if isinstance(img, list):
            return img[0] if img else ''
        return img or ''

    @staticmethod
    def _extract_price_from_offers(ld_obj):
        """Extract numeric price from JSON-LD offers if present."""
        offers = ld_obj.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get('price')
        if price is not None:
            try:
                return round(float(price), 2)
            except (ValueError, TypeError):
                pass
        return None

    def handle_error(self, failure):
        """Log request failures without crashing."""
        self.logger.warning(f"Request failed: {failure.request.url} - {failure.value}")
