"""Seed database with stores and categories for Côte d'Azur."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from .models import Store, Category, get_session, init_db
except ImportError:
    from db.models import Store, Category, get_session, init_db


STORES = [
    # Leroy Merlin - Côte d'Azur
    {"name": "Leroy Merlin Nice Lingostière", "chain": "leroy_merlin", "address": "230 Bd du Mercantour", "city": "Nice", "postal_code": "06200", "lat": 43.7102, "lng": 7.1928, "website": "https://www.leroymerlin.fr/magasin/nice-lingostiere/"},
    {"name": "Leroy Merlin Nice Saint-Isidore", "chain": "leroy_merlin", "address": "Av. Auguste Vérola", "city": "Nice", "postal_code": "06200", "lat": 43.7048, "lng": 7.1889, "website": "https://www.leroymerlin.fr/magasin/nice-st-isidore/"},
    {"name": "Leroy Merlin Antibes", "chain": "leroy_merlin", "address": "2141 Chemin de Saint-Claude", "city": "Antibes", "postal_code": "06600", "lat": 43.6205, "lng": 7.0715, "website": "https://www.leroymerlin.fr/magasin/antibes/"},
    {"name": "Leroy Merlin Mandelieu", "chain": "leroy_merlin", "address": "Rond-Point de la Frayère", "city": "Mandelieu-la-Napoule", "postal_code": "06210", "lat": 43.5445, "lng": 6.9371, "website": "https://www.leroymerlin.fr/magasin/mandelieu/"},
    {"name": "Leroy Merlin Toulon La Valette", "chain": "leroy_merlin", "address": "ZAC Valgora", "city": "La Valette-du-Var", "postal_code": "83160", "lat": 43.1376, "lng": 5.9831, "website": "https://www.leroymerlin.fr/magasin/toulon-la-valette/"},
    {"name": "Leroy Merlin Toulon La Garde", "chain": "leroy_merlin", "address": "Av. Léon Blum", "city": "La Garde", "postal_code": "83130", "lat": 43.1244, "lng": 6.0149, "website": "https://www.leroymerlin.fr/magasin/toulon-la-garde/"},

    # Castorama
    {"name": "Castorama Nice", "chain": "castorama", "address": "179 Bd du Mercantour", "city": "Nice", "postal_code": "06200", "lat": 43.7095, "lng": 7.1940, "website": "https://www.castorama.fr/magasin/nice"},
    {"name": "Castorama Mandelieu", "chain": "castorama", "address": "ZAC de l'Argile", "city": "Mandelieu-la-Napoule", "postal_code": "06210", "lat": 43.5512, "lng": 6.9401, "website": "https://www.castorama.fr/magasin/mandelieu"},
    {"name": "Castorama Toulon", "chain": "castorama", "address": "ZAC La Planquette", "city": "La Seyne-sur-Mer", "postal_code": "83500", "lat": 43.0960, "lng": 5.8710, "website": "https://www.castorama.fr/magasin/toulon"},

    # Brico Dépôt
    {"name": "Brico Dépôt Cagnes-sur-Mer", "chain": "brico_depot", "address": "ZI La Tourre", "city": "Cagnes-sur-Mer", "postal_code": "06800", "lat": 43.6620, "lng": 7.1390, "website": "https://www.bricodepot.fr/cagnessurmer/"},
    {"name": "Brico Dépôt Toulon", "chain": "brico_depot", "address": "ZAC de la Chaberte", "city": "La Valette-du-Var", "postal_code": "83160", "lat": 43.1420, "lng": 5.9780, "website": "https://www.bricodepot.fr/toulon/"},

    # Würth
    {"name": "Würth Nice", "chain": "wurth", "address": "14 Bd de l'Ariane", "city": "Nice", "postal_code": "06300", "lat": 43.7280, "lng": 7.3020, "website": "https://eshop.wurth.fr/"},
    {"name": "Würth Cannes", "chain": "wurth", "address": "ZI la Bocca", "city": "Cannes", "postal_code": "06150", "lat": 43.5510, "lng": 6.9520, "website": "https://eshop.wurth.fr/"},

    # Point P
    {"name": "Point P Nice", "chain": "point_p", "address": "Rue Catherine Ségurane", "city": "Nice", "postal_code": "06300", "lat": 43.7150, "lng": 7.2850, "website": "https://www.pointp.fr/"},
    {"name": "Point P Antibes", "chain": "point_p", "address": "ZI Les 3 Moulins", "city": "Antibes", "postal_code": "06600", "lat": 43.6180, "lng": 7.0680, "website": "https://www.pointp.fr/"},

    # Bricomarché
    {"name": "Bricomarché Grasse", "chain": "bricomarche", "address": "Route de Cannes", "city": "Grasse", "postal_code": "06130", "lat": 43.6520, "lng": 6.9230, "website": "https://www.bricomarche.com/"},

    # Brico io (Italie)
    {"name": "Brico io Imperia", "chain": "brico_io", "address": "Strada Provinciale 1", "city": "Imperia", "postal_code": "18100", "lat": 43.8830, "lng": 8.0260, "website": "https://www.bricoio.it/"},

    # Tollens
    {"name": "Tollens Nice", "chain": "tollens", "city": "Nice", "website": "https://www.tollens.com"},

    # Online stores
    {"name": "Sobrico Online", "chain": "sobrico", "city": "Cholet", "website": "https://www.sobrico.com"},
    {"name": "MaterielElectrique Online", "chain": "materiel_electrique", "city": "France", "website": "https://www.materielelectrique.com"},
    {"name": "Distriartisan Online", "chain": "distriartisan", "city": "Bordeaux", "website": "https://www.distriartisan.fr"},

    # New stores
    {"name": "Maxoutil Online", "chain": "maxoutil", "city": "France", "website": "https://www.maxoutil.com"},
    {"name": "Mr Bricolage Nice", "chain": "mr_bricolage", "city": "Nice", "website": "https://www.mr-bricolage.fr"},
    {"name": "123elec Online", "chain": "elec123", "city": "France", "website": "https://www.123elec.com"},

    # Chausson Matériaux
    {"name": "Chausson Matériaux Nice", "chain": "chausson", "city": "Nice", "website": "https://www.chausson.fr"},

    # Legallais
    {"name": "Legallais Online", "chain": "legallais", "city": "Caen", "website": "https://www.legallais.com"},
    # Cedeo
    {"name": "Cedeo Online", "chain": "cedeo", "city": "Paris", "website": "https://www.cedeo.fr"},
    # Point P
    {"name": "Point P Online", "chain": "pointp", "city": "Paris", "website": "https://www.pointp.fr"},
    # Bricozor
    {"name": "Bricozor Online", "chain": "bricozor", "city": "Paris", "website": "https://www.bricozor.com"},
]


CATEGORIES = [
    {"name": "Gros Oeuvre", "slug": "gros-oeuvre", "children": [
        {"name": "Ciment & Mortier", "slug": "ciment-mortier"},
        {"name": "Béton", "slug": "beton"},
        {"name": "Briques & Parpaings", "slug": "briques-parpaings"},
        {"name": "Acier & Ferraillage", "slug": "acier-ferraillage"},
        {"name": "Bois de charpente", "slug": "bois-charpente"},
        {"name": "Couverture & Toiture", "slug": "couverture-toiture"},
    ]},
    {"name": "Second Oeuvre", "slug": "second-oeuvre", "children": [
        {"name": "Isolation", "slug": "isolation"},
        {"name": "Plâtrerie & Cloisons", "slug": "platrerie-cloisons"},
        {"name": "Menuiserie", "slug": "menuiserie"},
        {"name": "Carrelage & Sol", "slug": "carrelage-sol"},
        {"name": "Façade & Enduit", "slug": "facade-enduit"},
    ]},
    {"name": "Plomberie", "slug": "plomberie", "children": [
        {"name": "Tuyauterie & Raccords", "slug": "tuyauterie-raccords"},
        {"name": "Robinetterie", "slug": "robinetterie"},
        {"name": "Sanitaire", "slug": "sanitaire"},
        {"name": "Chauffage", "slug": "chauffage"},
    ]},
    {"name": "Électricité", "slug": "electricite", "children": [
        {"name": "Câbles & Fils", "slug": "cables-fils"},
        {"name": "Appareillage", "slug": "appareillage"},
        {"name": "Tableau électrique", "slug": "tableau-electrique"},
        {"name": "Éclairage", "slug": "eclairage"},
    ]},
    {"name": "Outillage", "slug": "outillage", "children": [
        {"name": "Outillage à main", "slug": "outillage-main"},
        {"name": "Outillage électroportatif", "slug": "outillage-electroportatif"},
        {"name": "Visserie & Fixation", "slug": "visserie-fixation"},
        {"name": "Mesure & Traçage", "slug": "mesure-tracage"},
    ]},
    {"name": "Peinture", "slug": "peinture", "children": [
        {"name": "Peinture intérieure", "slug": "peinture-interieure"},
        {"name": "Peinture extérieure", "slug": "peinture-exterieure"},
        {"name": "Lasure & Vernis", "slug": "lasure-vernis"},
        {"name": "Enduit & Préparation", "slug": "enduit-preparation"},
    ]},
    {"name": "Quincaillerie", "slug": "quincaillerie", "children": [
        {"name": "Serrurerie", "slug": "serrurerie"},
        {"name": "Boulonnerie", "slug": "boulonnerie"},
        {"name": "Charnières & Ferrures", "slug": "charnieres-ferrures"},
    ]},
]


def seed_stores(session):
    existing = session.query(Store).count()
    if existing > 0:
        print(f"Stores already seeded ({existing} stores)")
        return

    for store_data in STORES:
        store = Store(**store_data)
        session.add(store)

    session.commit()
    print(f"Seeded {len(STORES)} stores")


def seed_categories(session):
    existing = session.query(Category).count()
    if existing > 0:
        print(f"Categories already seeded ({existing} categories)")
        return

    for cat_data in CATEGORIES:
        children = cat_data.pop("children", [])
        parent = Category(**cat_data)
        session.add(parent)
        session.flush()

        for child_data in children:
            child = Category(parent_id=parent.id, **child_data)
            session.add(child)

    session.commit()
    print(f"Seeded categories")


def seed_all():
    engine = init_db()
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    session = Session()

    seed_stores(session)
    seed_categories(session)

    session.close()
    print("Seeding complete!")


if __name__ == '__main__':
    seed_all()
