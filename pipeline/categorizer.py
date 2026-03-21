"""Auto-categorize products based on their name and category_path from spiders.

Maps products to our 37 predefined categories using keyword matching.

Usage:
    python -m pipeline.categorizer
"""
import sys
import os
import re
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import get_session, Product, StoreListing, Category

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mapping: keyword patterns -> category slug
# Order matters: more specific patterns first
CATEGORY_RULES = [
    # Peinture
    (r'peinture\s+int[eé]rieure|peinture\s+mur|peinture\s+plafond', 'peinture-interieure'),
    (r'peinture\s+ext[eé]rieure|peinture\s+fa[cç]ade', 'peinture-exterieure'),
    (r'lasure|vernis|vitrificateur', 'lasure-vernis'),
    (r'enduit|sous.couche|pr[eé]paration|rebouchage|lissage', 'enduit-preparation'),
    (r'peinture|rouleau|pinceau|b[âa]che|ruban.*masqu', 'peinture'),

    # Outillage
    (r'perceuse|visseuse|perforateur|meuleuse|ponceuse|scie\s+(?:sauteuse|circulaire|sabre)|rabot|d[eé]fonceuse|d[eé]coupeur|cloueur', 'outillage-electroportatif'),
    (r'tournevis|marteau|pince|cl[eé]|niveau|m[eè]tre|scie\s+(?!sauteuse|circulaire)|cisaille|lime|burin|spatule|truelle|cutter|couteau|equerre|compas', 'outillage-main'),
    (r'vis\b|boulon|[eé]crou|cheville|rivet|agrafe|clou|rondelle|tige\s+filet', 'visserie-fixation'),
    (r'mesure|tra[cç]age|laser|d[eé]tecteur|t[eé]l[eé]m[eè]tre', 'mesure-tracage'),
    (r'outillage|outil|servante|caisse.*outil|coffret|rangement.*atelier|[eé]tabli', 'outillage'),

    # Électricité
    (r'c[aâ]ble|gaine|fil\s+[eé]lectrique|c[aâ]blage', 'cables-fils'),
    (r'interrupteur|prise|appareillage|va.et.vient', 'appareillage'),
    (r'tableau\s+[eé]lectrique|disjoncteur|diff[eé]rentiel|module', 'tableau-electrique'),
    (r'[eé]clairage|ampoule|led|spot|plafonnier|lampe|luminaire|projecteur|r[eé]glette', 'eclairage'),
    (r'[eé]lectricit[eé]|domino|connecteur|bornier|goulotte', 'electricite'),

    # Plomberie
    (r'tuyau|raccord|tube|cuivre|per|multicouche|pvc|soudure|brasure', 'tuyauterie-raccords'),
    (r'robinet|mitigeur|robinetterie|vanne', 'robinetterie'),
    (r'wc|toilette|lavabo|vasque|baignoire|douche|sanitaire|siphon', 'sanitaire'),
    (r'chauffage|radiateur|chauffe.eau|thermostat|po[eê]le', 'chauffage'),
    (r'plomberie|joint|t[eé]flon|filasse', 'plomberie'),

    # Gros Oeuvre
    (r'ciment|mortier|ragr[eé]age', 'ciment-mortier'),
    (r'b[eé]ton|ferraillage|armature|treillis', 'beton'),
    (r'brique|parpaing|bloc|agglo', 'briques-parpaings'),
    (r'acier|fer|m[eé]tal|profil[eé]', 'acier-ferraillage'),
    (r'charpente|bois\s+(?:de\s+)?construct|madrier|bastaing|chevron|lambourde|poutre', 'bois-charpente'),
    (r'couverture|toiture|tuile|go[uû]tti[eè]re|ardoise|fa[iî]ti[eè]re', 'couverture-toiture'),
    (r'gros.oeuvre|coffrage|[eé]tai|[eé]chafaudage', 'gros-oeuvre'),

    # Second Oeuvre
    (r'isolation|isolant|laine.*(?:verre|roche)|polystyr[eè]ne|placo.*phonique', 'isolation'),
    (r'pl[aâ]tre|placo|cloison|rail|montant|ossature', 'platrerie-cloisons'),
    (r'menuiserie|fen[eê]tre|porte|volet|store|portail|escalier', 'menuiserie'),
    (r'carrelage|fa[iï]ence|mosaique|cr[eé]dence|sol.*mur', 'carrelage-sol'),
    (r'fa[cç]ade|cr[eé]pi|enduit.*fa[cç]ade|ravalement', 'facade-enduit'),
    (r'parquet|stratifi[eé]|lino|vinyl|moquette|sol\s+(?:pvc|souple|stratifi)', 'carrelage-sol'),

    # Quincaillerie
    (r'serrure|verrou|cylindre|poign[eé]e.*porte|cadenas', 'serrurerie'),
    (r'boulonnerie|goujon|tige', 'boulonnerie'),
    (r'charni[eè]re|ferrure|[eé]querr|support|console|cr[eé]maill[eè]re', 'charnieres-ferrures'),
    (r'quincaillerie', 'quincaillerie'),
]


def categorize_products():
    """Assign category_id to products based on their name and listing category_path."""
    session = get_session()

    # Load category slugs -> ids
    categories = session.query(Category).all()
    slug_to_id = {c.slug: c.id for c in categories}

    # Compile regex patterns
    compiled_rules = [(re.compile(pattern, re.IGNORECASE), slug) for pattern, slug in CATEGORY_RULES]

    # Get products without category
    products = session.query(Product).filter(Product.category_id.is_(None)).all()
    logger.info(f"Found {len(products)} products without category")

    categorized = 0
    for product in products:
        # Try to categorize from product name
        text = product.name or ''

        # Also check category_path from listings
        listing = session.query(StoreListing).filter(StoreListing.product_id == product.id).first()
        if listing and listing.category_path:
            text += ' ' + listing.category_path

        text = text.lower()

        for pattern, slug in compiled_rules:
            if pattern.search(text):
                cat_id = slug_to_id.get(slug)
                if cat_id:
                    product.category_id = cat_id
                    categorized += 1
                    break

    session.commit()
    logger.info(f"Categorized {categorized}/{len(products)} products")

    # Log stats per category
    for cat in session.query(Category).filter(Category.parent_id.isnot(None)).all():
        count = session.query(Product).filter(Product.category_id == cat.id).count()
        if count > 0:
            logger.info(f"  {cat.name}: {count} products")


if __name__ == '__main__':
    categorize_products()
