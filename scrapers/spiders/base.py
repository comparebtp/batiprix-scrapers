"""Base spider with common logic for all BTP store spiders."""
import scrapy
from scrapers.items import BTPProductItem


class BaseBTPSpider(scrapy.Spider):
    """Base class for all BTP store spiders."""

    # Override in subclasses
    store_chain = None  # "leroy_merlin", "castorama"...

    custom_settings = {
        'DOWNLOAD_DELAY': 2.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 2,
    }

    def make_item(self, **kwargs):
        """Create a BTPProductItem with store_chain pre-filled."""
        item = BTPProductItem()
        item['store_chain'] = self.store_chain
        for key, value in kwargs.items():
            if value is not None:
                item[key] = value
        return item

    def parse_price(self, price_str):
        """Parse a French-formatted price string to float.

        Handles: "12,50 €", "1 234,56€", "12.50", etc.
        """
        if not price_str:
            return None
        import re
        # Remove currency symbols and whitespace
        price_str = re.sub(r'[€$\s\xa0]', '', str(price_str))
        # Handle French format: 1.234,56 or 1 234,56
        price_str = re.sub(r'\.(?=\d{3})', '', price_str)  # remove thousands separator
        price_str = price_str.replace(',', '.')
        try:
            return round(float(price_str), 2)
        except ValueError:
            return None
