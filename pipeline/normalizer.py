"""Product name normalizer for cross-store matching."""
import re
from unidecode import unidecode


def normalize_product_name(name: str) -> str:
    """Create a canonical product name for matching.

    Steps:
    1. Lowercase
    2. Remove accents
    3. Remove common filler words
    4. Normalize whitespace
    5. Sort key terms for order-independent matching
    """
    if not name:
        return ""

    name = name.lower().strip()
    name = unidecode(name)

    # Remove common filler words
    filler_words = {
        'le', 'la', 'les', 'de', 'du', 'des', 'un', 'une',
        'et', 'ou', 'en', 'pour', 'avec', 'sans', 'sur',
    }
    words = name.split()
    words = [w for w in words if w not in filler_words]

    # Remove special characters but keep numbers and units
    name = ' '.join(words)
    name = re.sub(r'[^\w\s\d.,/]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def extract_dimensions(name: str) -> dict:
    """Extract dimensions from product name.

    Returns dict with keys like 'length', 'width', 'height', 'diameter', 'thickness'.
    """
    dims = {}

    # Pattern: 100x50x20mm or 100 x 50 x 20 mm
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*(?:x\s*(\d+(?:[.,]\d+)?)\s*)?(?:mm|cm|m)\b', name, re.I)
    if match:
        dims['length'] = float(match.group(1).replace(',', '.'))
        dims['width'] = float(match.group(2).replace(',', '.'))
        if match.group(3):
            dims['height'] = float(match.group(3).replace(',', '.'))

    # Diameter: Ø12mm or diam 12
    match = re.search(r'(?:ø|diam(?:etre)?\.?\s*)(\d+(?:[.,]\d+)?)\s*(?:mm|cm)?\b', name, re.I)
    if match:
        dims['diameter'] = float(match.group(1).replace(',', '.'))

    # Thickness: ep. 12mm or épaisseur 12
    match = re.search(r'(?:ep\.?|epaisseur)\s*(\d+(?:[.,]\d+)?)\s*(?:mm|cm)?\b', name, re.I)
    if match:
        dims['thickness'] = float(match.group(1).replace(',', '.'))

    return dims


def extract_volume_weight(name: str) -> dict:
    """Extract volume or weight from product name."""
    result = {}

    # Weight: 25kg, 5 kg
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*kg\b', name, re.I)
    if match:
        result['weight_kg'] = float(match.group(1).replace(',', '.'))

    # Volume: 5L, 10 litres
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:l|litres?)\b', name, re.I)
    if match:
        result['volume_l'] = float(match.group(1).replace(',', '.'))

    # Length in meters: 2.5m, 3 mètres
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:m|metres?)\b', name, re.I)
    if match and 'mm' not in name[match.start():match.end()+2]:
        result['length_m'] = float(match.group(1).replace(',', '.'))

    return result
