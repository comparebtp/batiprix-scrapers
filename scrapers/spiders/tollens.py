"""Spider for Tollens - tollens.com

No anti-bot protection. Standard HTML with prices.
Structure:
- Card: .Product.ProductCard
- Title: .Product-title
- Price: .Product-clubPrice (ancien prix), .Product-promoPrice (prix promo)
- Image: .Product-image img
- Link: a inside card
- Pagination: ?p=2, ?p=3...
- Categories: /catalogue/CATEGORY
"""
import re
from urllib.parse import urlparse

import scrapy
from scrapers.spiders.base import BaseBTPSpider


class TollensSpider(BaseBTPSpider):
    name = 'tollens'
    store_chain = 'tollens'
    allowed_domains = ['tollens.com']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_urls = set()

    start_categories = [
        ('/catalogue/peintures-interieures', 'Peintures intérieures'),
        ('/catalogue/peintures-facades', 'Peintures façades'),
        ('/catalogue/peintures-bois-lasures', 'Peintures bois & lasures'),
        ('/catalogue/peintures-metal', 'Peintures métal'),
        ('/catalogue/outillage-du-peintre', 'Outillage du peintre'),
        ('/catalogue/protection-du-chantier', 'Protection du chantier'),
        ('/catalogue/papiers-peints', 'Papiers peints'),
        ('/catalogue/revetements-de-sols', 'Revêtements de sols'),
        ('/catalogue/peintures', 'Toutes peintures'),
        ('/catalogue/outillage-et-fournitures', 'Outillage et fournitures'),
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
    }

    def start_requests(self):
        for path, cat_name in self.start_categories:
            url = f'https://www.tollens.com{path}'
            yield scrapy.Request(
                url,
                callback=self.parse_category,
                meta={'category_path': [cat_name]},
            )

    def parse_category(self, response):
        category_path = response.meta.get('category_path', [])

        # Extract product cards - article.Product.ProductCard
        cards = response.css('article.ProductCard')
        if not cards:
            cards = response.css('article.Product')
        self.logger.info(f"Found {len(cards)} products on {response.url}")

        for card in cards:
            # Title from h3.Product-title or a.Product-titleLink
            title = card.css('h3.Product-title::text, a.Product-titleLink::text').get('').strip()
            if not title:
                title = card.css('h2::text, h3::text').get('').strip()

            if not title:
                continue

            # Price - discounted first, then regular
            price_text = card.css('.Product-priceData--discounted::text').get('')
            if not price_text:
                price_text = card.css('.Product-priceData::text').get('')
            if not price_text:
                price_text = card.css('.Product-clubPrice::text').get('')
            price = self.parse_price(price_text.strip()) if price_text else None

            # Old price (striked)
            old_price_text = card.css('.Product-priceData--striked::text').get('')
            old_price = self.parse_price(old_price_text.strip()) if old_price_text else None

            # URL
            link = card.css('a.Product-titleLink::attr(href), a::attr(href)').get('')
            url = response.urljoin(link) if link else ''

            # Image
            img = card.css('.Product-MediaContainer img::attr(src)').get('')
            if not img:
                img = card.css('img::attr(src), img::attr(data-src), img::attr(data-lazy-src)').get('')

            # Promo info
            promo = card.css('.Product-promotionPercentage::text').get('').strip()

            # Description
            desc = card.css('.Product-intro::text, p.Product-intro::text').get('').strip()

            # Generate SKU from URL path slug
            sku = ''
            if url:
                path = urlparse(url).path.strip('/')
                slug = path.split('/')[-1] if path else ''
                if slug:
                    sku = f'tollens-{slug}'

            # Try to extract EAN from product card data attributes
            ean = card.attrib.get('data-ean', '') or card.attrib.get('data-gtin', '')
            if not ean:
                ean = card.css('[data-ean]::attr(data-ean), [data-gtin]::attr(data-gtin)').get('')

            if title:
                item = self.make_item(
                    product_name=title,
                    product_url=url,
                    sku=sku,
                    ean=ean if ean else None,
                    manufacturer='Tollens',
                    price=price,
                    image_url=img,
                    category_path=category_path,
                    description=desc,
                )
                if old_price:
                    item['old_price'] = old_price
                yield item

        # Pagination
        next_page = response.css(
            'a[rel="next"]::attr(href), '
            '.Pagination a.next::attr(href), '
            '[class*=pagination] a[class*=next]::attr(href)'
        ).get()

        if next_page:
            yield scrapy.Request(
                response.urljoin(next_page),
                callback=self.parse_category,
                meta={'category_path': category_path},
            )
        else:
            # Try numbered pagination
            current_page = response.url
            page_match = re.search(r'[?&]p=(\d+)', current_page)
            current_num = int(page_match.group(1)) if page_match else 1

            # Check if there's a next page number link
            page_links = response.css('a[href*="?p="]::attr(href), a[href*="&p="]::attr(href)').getall()
            for pl in page_links:
                pm = re.search(r'[?&]p=(\d+)', pl)
                if pm and int(pm.group(1)) == current_num + 1:
                    yield scrapy.Request(
                        response.urljoin(pl),
                        callback=self.parse_category,
                        meta={'category_path': category_path},
                    )
                    break

        # Subcategories
        subcats = response.css('a[href*="/catalogue/"]::attr(href)').getall()
        self.seen_urls.add(response.url)
        for href in subcats:
            full_url = response.urljoin(href)
            if full_url not in self.seen_urls and '/catalogue/' in href and '?' not in href:
                self.seen_urls.add(full_url)
                sub_name = href.strip('/').split('/')[-1].replace('-', ' ').title()
                yield scrapy.Request(
                    full_url,
                    callback=self.parse_category,
                    meta={'category_path': category_path + [sub_name]},
                )
