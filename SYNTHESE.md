# SYNTHESE PROJET BATIPRIX / COMPAREBTP

> Document de reference exhaustif — Derniere mise a jour : 21 mars 2026

---

## 1. Etat du projet

### Identite
- **Nom** : BatiPrix (anciennement CompareBTP)
- **Concept** : Comparateur de prix de materiaux et outillage BTP, cible geographique Cote d'Azur / PACA
- **Email projet** : batiprix@outlook.fr / `CompareBTP!2026#Azur`
- **Domaine** : batiprix.pro (achete le 20/03/2026 chez OVH, 3,59 EUR TTC, renouvellement mars 2027, 26,29 EUR/an)

### URLs
| Environnement | URL |
|---|---|
| Production (Vercel) | https://comparebtp.vercel.app |
| Domaine custom | https://batiprix.pro (DNS a configurer vers Vercel) |
| Ancien (Netlify) | https://remarkable-duckanoo-7dc54e.netlify.app |
| Local | http://localhost:3000 |

### Stack technique

**Scraping (backend Python)** :
- Python 3.11
- Scrapy + scrapy-playwright (pour les sites JS-rendered)
- SQLAlchemy ORM
- rapidfuzz (matching fuzzy)
- unidecode (normalisation noms)

**Site web (frontend)** :
- Next.js (App Router)
- Tailwind CSS
- TypeScript
- Deploiement : Vercel (plan Hobby gratuit)

**Base de donnees** :
- SQLite locale (dev) : `data/btp_comparateur.db`
- PostgreSQL Neon (production) : projet `soft-snow-35285422`, region AWS Frankfurt
- Connection string : voir .env ou GitHub Secrets (ne pas committer)
- Plan : Free (0.5 GB)

### Donnees en base (production Neon)
- **468 produits** canoniques
- **468 listings** (liens produit-magasin)
- **17 magasins** enregistres
- **37 categories** predefinies
- **468 entrees price_history**

### Hebergement et comptes
| Service | Compte | Usage |
|---|---|---|
| Vercel | GitHub OAuth (comparebtp) | Hebergement Next.js |
| Netlify | batiprix@outlook.fr | Ancien hebergement (encore actif) |
| Neon | batiprix@outlook.fr | BDD PostgreSQL |
| GitHub | comparebtp / batiprix@outlook.fr | Repo code |
| OVH | batiprix@outlook.fr (NIC: at237190-ovh) | Nom de domaine |
| Google Search Console | batiprix@outlook.fr | SEO |

---

## 2. Schema de base de donnees

### Tables

**`stores`** : Magasins physiques ou en ligne
- id, name, chain (ex: "brico_depot"), address, city, postal_code, lat, lng, website

**`categories`** : Arborescence de categories (37 categories, parent_id pour hierarchie)
- id, name, slug, parent_id

**`products`** : Produits canoniques (un produit = un objet reel, potentiellement vendu dans N magasins)
- id, name, canonical_name, slug, ean, brand, manufacturer, manufacturer_ref
- category_id, unit, description, image_url
- specifications (JSON), volume, color, weight, dimensions, pack_size, finish
- min_price, max_price, listing_count (denormalises)
- updated_at

**`store_listings`** : Un produit dans un magasin specifique (prix, stock, URL)
- id, store_id, product_id (nullable jusqu'au matching)
- store_product_name, store_product_url, store_sku, store_ean, store_manufacturer_ref
- current_price, old_price, unit_price, unit_label, in_stock
- category_path, image_url, last_scraped_at
- Contrainte unique : (store_id, store_sku)

**`price_history`** : Historique des prix (un enregistrement par changement de prix)
- id, listing_id, price, scraped_at

**`scrape_runs`** : Journal des executions de spiders
- id, started_at, finished_at, spider_name, items_scraped, items_new, items_updated, errors, status

---

## 3. Scrapers — Etat de chaque spider

### 3.1 Brico Depot (`brico_depot.py`)
- **Status** : FONCTIONNEL
- **Produits scrapes** : 451 en base
- **Methode** : HTTP pur (pas de Playwright), sitemaps XML (5 fichiers, ~22 000 produits total)
- **Filtrage** : Mots-cles BTP dans l'URL (~65 keywords)
- **Store selection** : Cookie `USER_LAST_VISITED_STORE_ID=1944` + remplacement `/catalogue/` par `/nice-lingostiere/`
- **Store Nice** : Depot Nice-Lingostiere, ID 1944, slug `nice-lingostiere`
- **Anti-bot** : Aucun (robots.txt respecte)
- **Donnees extraites** : JSON-LD Product (name, sku, gtin13, brand, price, image, additionalProperty pour specs, weight, dimensions, color, material)
- **Delay** : 1.5s, 3 requetes concurrentes max
- **Stores France** : 127 depots recenses dans `data/bricodepot_stores.json`

### 3.2 Tollens (`tollens.py`)
- **Status** : FONCTIONNEL
- **Methode** : HTTP pur, navigation par categories (10 categories de peinture)
- **Store selection** : Prix nationaux, pas de selection par magasin
- **Anti-bot** : Aucun
- **Donnees extraites** : Nom, prix (normal + promo + barre), image, URL, description, EAN (si data-attribute)
- **Manufacturer** : Force a "Tollens"
- **Pagination** : `?p=N` + sous-categories
- **Delay** : 2s, 2 requetes concurrentes

### 3.3 Wurth (`wurth.py`)
- **Status** : PARTIELLEMENT FONCTIONNEL (1 260 scrapes, 17 uniques — spider a ameliorer, trop de doublons)
- **Methode** : HTTP pur, double strategie :
  1. API Suggest (`ViewParametricSearch-Suggest`) avec ~40 termes de recherche BTP
  2. Crawl des 14 categories top-level
- **Store selection** : Prix B2B par compte, pas de selection magasin
- **Anti-bot** : Aucun (robots.txt ignore)
- **Donnees extraites** : JSON-LD Product/ProductGroup (sku, gtin13, name, variants, availability, price HT si disponible)
- **Prix** : Souvent absents (necessitent un login B2B). Extraction du prix HT depuis le texte en fallback
- **Deduplication** : `seen_refs` et `seen_group_ids` pour eviter les doublons (ameliorable)
- **Delay** : 2.5s, 2 requetes concurrentes

### 3.4 Castorama (`castorama.py`)
- **Status** : BLOQUE (DataDome/Cloudflare)
- **Methode** : Playwright (JS rendering obligatoire, SPA React)
- **Store selection** : API Kingfisher, magasin Antibes ID 1429
- **Anti-bot** : Cloudflare agressif — requiert Playwright headed
- **Donnees extraites** : dataLayer GA ecommerce (name, price, sku, brand, category) + fallback DOM parsing
- **Categories couvertes** : 30 sous-categories BTP (outillage, quincaillerie, peinture, electricite, plomberie, materiaux, sol/mur, salle de bains, jardin)
- **Delay** : 4s, 1 requete concurrente
- **Solution envisagee** : Flux Awin (candidature refusee) ou Affilae

### 3.5 Leroy Merlin (`leroy_merlin.py`)
- **Status** : BLOQUE (DataDome)
- **Methode** : HTTP avec User-Agent Googlebot — sitemaps accessibles mais pages produit bloquees (403)
- **Store selection** : Slug dans l'URL (ex: `/nice/`), mais pages inaccessibles
- **Anti-bot** : DataDome — bloque meme avec Googlebot UA sur les pages produit
- **Donnees extraites** : En cas d'acces : JSON-LD, __NEXT_DATA__. En fallback : nom + reference extraits de l'URL (`/produits/NOM-REFXXXXXXXX.html`)
- **Sitemaps** : 99 fichiers `sitemap-product{N}.xml`, par defaut 20 parcourus
- **Solution envisagee** : Flux affiliation via Affilae (candidature envoyee le 20/03/2026, en attente)
- **Delay** : 1s, 2 requetes concurrentes

### 3.6 Bricorama (`bricorama.py`)
- **Status** : A TESTER (spider ecrit, pas encore execute en production)
- **Methode** : Playwright headed + stealth (Cloudflare)
- **Store selection** : Pas de mecanisme identifie
- **Anti-bot** : Cloudflare — contourne avec Playwright headed + `--disable-blink-features=AutomationControlled`
- **Donnees extraites** : DOM parsing (.ProductTile), prix format "399 EUR 00"
- **Recherche** : 15 termes BTP via `/catalogsearch/result/`
- **Delay** : 3s, 1 requete concurrente

### 3.7 Bricomarche (`bricomarche.py`)
- **Status** : A TESTER
- **Methode** : Playwright headed (Cloudflare)
- **Store selection** : Cookie/session, magasin Nice 06200 (pas encore configure dans le spider)
- **Anti-bot** : Cloudflare — contourne avec Playwright headed
- **Donnees extraites** : DOM parsing (selectors generiques product-card, ProductCard, etc.)
- **Categories** : 16 categories BTP predefinies
- **Delay** : 3s, 1 requete concurrente
- **Solution envisagee** : Flux Kwanko (compte cree, pas encore postule)

### 3.8 Kiloutou (`kiloutou.py`)
- **Status** : A TESTER (spider ecrit pour la location de materiel)
- **Methode** : Playwright headed, recherche par termes (25 termes)
- **Store selection** : Non applicable (location, tarifs nationaux)
- **Donnees extraites** : Nom, prix de location (EUR/jour HT), image, URL
- **Note** : Exclu du pipeline daily (location, pas vente au detail)
- **Delay** : 3s, 1 requete concurrente

### 3.9 Loxam (`loxam.py`)
- **Status** : A TESTER (spider ecrit pour la location de materiel)
- **Methode** : Playwright headed, recherche par termes (15 termes)
- **Store selection** : Non applicable (location)
- **Donnees extraites** : Nom, prix de location (EUR/jour HT), image, URL
- **Note** : Exclu du pipeline daily (location, pas vente au detail)
- **Delay** : 3s, 1 requete concurrente

### Spider de base (`base.py`)
- Classe `BaseBTPSpider` : fournit `make_item()` (creation BTPProductItem avec store_chain pre-rempli) et `parse_price()` (parsing prix format francais : "1 234,56 EUR" -> 1234.56)

### Items Scrapy (`items.py`)
- `BTPProductItem` : store_chain, store_name, product_name, product_url, sku, ean, manufacturer, manufacturer_ref, price, unit_price, unit_label, old_price, category_path, description, image_url, in_stock, specifications

---

## 4. Store Selection par enseigne — Tableau complet

| Enseigne | Mecanisme | Magasin 06 | ID/Code | Status |
|---|---|---|---|---|
| **Brico Depot** | Cookie `USER_LAST_VISITED_STORE_ID` + prefixe URL | Nice-Lingostiere | 1944 | Implemente |
| **Castorama** | API Kingfisher | Antibes | 1429 | Identifie, spider bloque |
| **Leroy Merlin** | Slug URL (`/nice/`) | Nice | slug `nice` | Identifie, spider bloque |
| **Bricomarche** | Cookie/session magasin | Nice 06200 | Non determine | A implementer |
| **Mr. Bricolage** | shopId param | Non determine | S1638 (exemple) | Non implemente |
| **Point P** | Agence dans l'URL, login pro requis | Non determine | Agence 4308 | Login obligatoire |
| **Tollens** | Pas de selection (prix nationaux) | N/A | N/A | Fonctionnel |
| **Wurth** | Compte B2B (prix par client) | N/A | N/A | Pas de prix publics |
| **Weldom** | Selection magasin sur site | Le Rouret / Menton | Non determine | Non implemente |
| **ManoMano** | En ligne, pas de magasin | N/A | N/A | Flux Awin envisage |
| **Bricorama** | Non identifie | N/A | N/A | A investiguer |
| **Kiloutou** | Location, tarifs nationaux | N/A | N/A | N/A |
| **Loxam** | Location, tarifs nationaux | N/A | N/A | N/A |

---

## 5. Pipeline de donnees

### 5.1 Scrapy Pipelines (`scrapers/pipelines.py`)

Trois pipelines chaines dans l'ordre :

1. **ValidationPipeline** : Rejette les items sans nom, sans prix, prix <= 0 ou > 100 000 EUR, sans store_chain. Nettoie unit_price.

2. **NormalizationPipeline** : Decode entites HTML, normalise espaces, valide format EAN (13 chiffres), normalise nom fabricant (Title Case), convertit category_path string -> liste.

3. **DatabasePipeline** : Upsert dans `store_listings` (cle unique store_id + store_sku). Si listing existe : mise a jour prix + enregistrement PriceHistory si changement. Si nouveau : creation listing + premier PriceHistory. Propage brand/description vers Product lie. Extrait specs via `spec_extractor` et remplit les champs denormalises du Product. Commit tous les 100 items. Rollback en cas d'erreur.

### 5.2 Extracteur de specifications (`pipeline/spec_extractor.py`)

Extraction par regex depuis le nom du produit. Champs extraits :
- **volume** : "2.5 L", "10 litres"
- **weight** : "25 kg", "500 g"
- **dimensions** : "100x50x20mm" (LxWxH)
- **diameter** : "O12mm"
- **thickness** : "ep. 12mm"
- **length** : "L. 2.5 m"
- **power** : "750 W", "18 V" (filtre >= 10V)
- **battery** : "5 Ah"
- **pack_size** : "lot de 10", "500 pieces"
- **color** : 50+ couleurs FR (blanc, gris anthracite, chene, chrome...)
- **finish** : satin, mat, brillant, laque, brosse, verni, monocouche...
- **material** : 30+ materiaux (inox, PVC, cuivre, beton, BA13...)
- **bit_type** : PH, PZ, Torx, SL, hexagonal...
- **tool_type** : sans fil, percussion, SDS-Plus, brushless...
- **saw_type, plier_type, drill_type, disc_type** : sous-types specifiques
- **grain** : grain abrasif (P80, grain 120...)
- **torque** : "45 Nm"
- **speed** : "2800 tr/min"
- **chuck** : "mandrin 13mm"
- **key_size, drive_size** : taille cle, empreinte douille (1/4, 1/2...)
- **teeth** : nombre de dents (scie, lame)
- **max_load** : "charge max 150 kg"
- **steps** : nombre de marches (echelle)
- **pressure** : "8 bars"
- **section** : "2.5 mm2" (cable electrique)
- **amperage** : "16 A"
- **ip_rating** : "IP65"

Les specs fournies par le spider (JSON-LD additionalProperty etc.) ont priorite sur l'extraction depuis le nom.

**Resultats** : 2 450 / 4 111 produits avec specs extraites (selon les dernieres executions)

### 5.3 Matcher cross-enseigne (`pipeline/matcher.py`)

Trois strategies de matching, executees dans l'ordre :

1. **EAN** : Correspondance exacte sur code-barres EAN-13. Si pas de Product existant, en cree un nouveau.

2. **Manufacturer ref** : Correspondance exacte sur reference fabricant.

3. **Fuzzy name** (spec-aware) :
   - **Blocking** : index par les 2 premiers mots significatifs du nom normalise (O(n) au lieu de O(n2))
   - **Spec compatibility** : rejection immediate si couleur, volume, dimensions, poids, finition ou puissance different
   - **Score** : `fuzz.token_sort_ratio` (rapidfuzz), seuil 85%
   - Si pas de match : creation d'un nouveau Product canonique

Fonctions supplementaires :
- `unmatch_bad_matches()` : detecte et casse les matchs incorrects (produits avec specs incompatibles groupes ensemble)
- `fix_existing_matches()` : unmatch + rematch + mise a jour champs denormalises

### 5.4 Normaliseur de noms (`pipeline/normalizer.py`)
- Lowercase + suppression accents (unidecode)
- Suppression mots de liaison (le, la, de, du, pour, avec, etc.)
- Suppression caracteres speciaux (sauf chiffres et unites)
- Extraction dimensions et volume/poids depuis le nom

### 5.5 Categoriseur (`pipeline/categorizer.py`)
- 37 categories predefinies organisees en arborescence
- Matching par regex sur le nom du produit + category_path des listings
- Categories : peinture (interieure/exterieure/lasure/enduit), outillage (electroportatif/main/visserie/mesure), electricite (cables/appareillage/tableau/eclairage), plomberie (tuyauterie/robinetterie/sanitaire/chauffage), gros oeuvre (ciment/beton/briques/acier/bois/toiture), second oeuvre (isolation/platrerie/menuiserie/carrelage/facade), quincaillerie (serrurerie/boulonnerie/charnieres)

### 5.6 Validateur (`pipeline/validator.py`)
- Rapport de qualite : prix min/max/moyen/median, prix suspects (< 0.10 EUR, > 10 000 EUR)
- Couverture identifiants : % avec EAN, % avec ref fabricant, % avec categorie
- Detection doublons de noms
- Stock : % en stock

### 5.7 Importeur de flux Awin (`pipeline/awin_feed.py`)
- Pret a utiliser mais en attente d'approbation affiliation
- Supporte CSV et XML
- Mapping des noms de champs Awin (multiples conventions)
- Import par batch de 500 avec commit intermediaire
- Chains supportees : leroy_merlin, castorama, manomano

### 5.8 Pipeline quotidien (`pipeline/daily_run.py`)
- Execute les 7 spiders retail (exclut kiloutou, loxam)
- Timeout 30 min par spider
- Enchaine : spiders -> matching -> categorisation -> generation slugs -> mise a jour champs denormalises -> extraction marques
- Extraction marques : 35 marques connues (Bosch, Makita, DeWalt, Hilti, Stanley, Facom, etc.)
- Log complet avec stats (items scrapes, erreurs, totaux en base)

---

## 6. Affiliation

### Awin
- **Compte** : batiprix@outlook.fr / `CompareBTP!2026#Azur`
- **Status** : REFUSE le 18/03/2026 — site juge trop basique
- **Raison** : site pas assez complet au moment de la candidature
- **Action** : Repostuler quand le site sera plus complet
- **Programmes cibles** : Castorama (ID 6991), Brico Depot (Kingfisher), ManoMano (ID 17547), Wurth, Leroy Merlin

### Affilae
- **Compte** : batiprix@outlook.fr / `CompareBTP!2026#Azur`
- **URL** : https://app.affilae.com
- **Status** : INSCRIT + POSTULE a Leroy Merlin le 20/03/2026
- **En attente** : reponse de Leroy Merlin (~60 000 produits potentiels)
- **Autres programmes** : Wurth Modyf (candidature envoyee)

### Kwanko
- **Compte** : batiprix@outlook.fr / `CompareBTP!2026#Azur`
- **URL** : https://publisher.kwanko.com
- **Type** : Self employed / Generalist price comparison
- **Status** : INSCRIT le 20/03/2026
- **A faire** : Postuler a Bricomarche (~5 000 produits)

---

## 7. SEO

### Google Search Console
- Verification : meta tag `J17mXRcWkdQPf9e3V3PUMA_nHG1GU0-qpqKTlbrt6Do`
- Sitemap soumis : `sitemap.xml` (dynamique, genere par Next.js)
- Pages dans le sitemap : 12 statiques + 12 guides + top 500 produits + toutes categories

### IndexNow
- 24 URLs soumises a Bing et Yandex

### Schema.org (donnees structurees)
- `Product` : sur les pages produit
- `BreadcrumbList` : navigation
- `Article` : sur les guides
- `FAQPage` : sur la FAQ
- `WebSite` : sur l'accueil (avec SearchAction)
- `Organization` : informations entreprise

### OpenGraph
- Image OG : creee et deployee (`/og-image.png`, 1200x630)
- Metadata OG completes : titre, description, URL, locale fr_FR

### Canonical URLs
- Corrigees sur toutes les pages
- Base URL : `https://batiprix.pro`

### Robots
- `index: true, follow: true` sur toutes les pages

---

## 8. Site Web — Pages et features

### Pages publiques

| Route | Description |
|---|---|
| `/` | Page d'accueil : hero, barre de recherche, produits populaires, categories, carousel logos enseignes |
| `/recherche` | Recherche de produits avec filtres |
| `/categories` | Liste des 37 categories |
| `/categories/[slug]` | Produits d'une categorie |
| `/produit/[slug]` | Fiche produit : comparaison prix entre magasins, historique prix, specs |
| `/magasins` | Carte/liste des magasins partenaires |
| `/guides` | Liste des 12 guides BTP |
| `/guides/[slug]` | Article guide (perceuse, peinture, renovation SDB, materiaux Cote d'Azur, etc.) |
| `/faq` | Questions frequentes |
| `/a-propos` | Presentation du service |
| `/contact` | Formulaire de contact |
| `/panier` | Panier (fonctionnalite future) |
| `/mentions-legales` | Mentions legales |
| `/cgu` | Conditions generales d'utilisation |
| `/confidentialite` | Politique de confidentialite |
| `/cookies` | Politique cookies |

### 12 Guides SEO
1. Comment choisir sa perceuse
2. Prix des materiaux de construction sur la Cote d'Azur
3. Guide peinture interieure
4. Renovation salle de bain budget
5. Meilleurs magasins BTP a Nice
6. Isoler sa maison sur la Cote d'Azur
7. Comparatif visserie et fixation
8. Outillage electroportatif pro
9. Carrelage sol et mur guide
10. Electricite maison normes et prix
11. Acheter des materiaux en Italie (frontiere)
12. Economiser sur les travaux de renovation

### API Routes

| Route | Description |
|---|---|
| `/api/products` | Liste produits (paginee, filtrable) |
| `/api/products/[slug]` | Detail produit + listings |
| `/api/categories` | Liste categories |
| `/api/search` | Recherche full-text |
| `/api/autocomplete` | Autocompletion recherche |
| `/api/stores` | Liste magasins |

### Composants React

| Composant | Description |
|---|---|
| `Navbar` | Barre de navigation responsive |
| `Footer` | Pied de page avec liens |
| `SearchBar` | Barre de recherche avec autocompletion |
| `ProductCard` | Carte produit (image, nom, prix, badge promo) |
| `PriceTable` | Tableau comparatif des prix par enseigne |
| `PriceChart` | Graphique d'historique des prix |
| `FilterSidebar` | Filtres lateraux (categorie, prix, marque, magasin) |
| `Pagination` | Pagination des resultats |
| `LogoCarousel` | Carousel des logos enseignes partenaires |
| `CookieBanner` | Bandeau cookies RGPD |

### Features implementees
- Recherche produits avec autocompletion
- Comparaison de prix cross-enseigne (tableau comparatif)
- Historique des prix (graphique)
- Filtres : categorie, fourchette de prix, marque, magasin
- Panier (CartProvider avec context React)
- SEO complet (meta, OG, Schema.org, sitemap dynamique, canonical)
- Responsive design (Tailwind)
- Bandeau cookies RGPD

---

## 9. Bugs corriges

- **Wurth spider doublons** : 1 260 scrapes pour 17 uniques — deduplication `seen_refs` / `seen_group_ids` ajoutee mais insuffisante, a ameliorer
- **Matching faux positifs** : produits de couleurs/volumes differents groupes ensemble — corrige avec `_specs_compatible()` et seuil monte de 82% a 85%
- **Canonical URLs** : pointaient vers comparebtp.vercel.app au lieu de batiprix.pro — corrige
- **OG image** : manquante — creee et deployee
- **Prix Brico Depot** : affichaient les prix du depot par defaut (Artigues) au lieu de Nice — corrige avec cookies store selection

---

## 10. Credentials complets

### Services principaux
| Service | Login | MDP |
|---|---|---|
| Email Outlook | batiprix@outlook.fr | `CompareBTP!2026#Azur` |
| Netlify | batiprix@outlook.fr | `CompareBTP!2026#Azur` |
| Neon | batiprix@outlook.fr | `CompareBTP!2026#Neon` |
| GitHub | comparebtp | `CompareBTP!2026#GitHub` |
| OVH | batiprix@outlook.fr (NIC: at237190-ovh) | `CompareBTP!2026#Azur` |
| Awin | batiprix@outlook.fr | `CompareBTP!2026#Azur` |
| Affilae | batiprix@outlook.fr | `CompareBTP!2026#Azur` |
| Kwanko | batiprix@outlook.fr | `CompareBTP!2026#Azur` |
| Vercel | via GitHub OAuth | N/A |
| Google Search Console | batiprix@outlook.fr | N/A |

### Tokens et cles
- **GitHub PAT** : voir memory/comparebtp-credentials.md (ne pas committer)
- **DATABASE_URL (Neon)** : voir .env ou GitHub Secrets (ne pas committer)

---

## 11. TODO / Prochaines etapes

### Priorite haute
- [ ] **Configurer DNS OVH** : pointer batiprix.pro vers Vercel
- [ ] **Repostuler Awin** : quand le site a plus de contenu et de produits
- [ ] **Attendre reponse Affilae/Leroy Merlin** : si accepte -> importer flux ~60 000 produits
- [ ] **Postuler Bricomarche sur Kwanko** : ~5 000 produits potentiels
- [ ] **Ameliorer spider Wurth** : resoudre le probleme de doublons (1 260 -> 17 uniques)
- [ ] **Lancer les spiders non testes** : bricorama, bricomarche, kiloutou, loxam

### Priorite moyenne
- [ ] **Enrichir les donnees** : augmenter le nombre de produits (actuellement 468, objectif > 3 000)
- [ ] **Automatiser le pipeline daily** : cron job ou GitHub Actions
- [ ] **Ajouter des enseignes** : Mr. Bricolage, Point P, Weldom, ManoMano
- [ ] **Implementer le panier** : fonctionnalite de comparaison et liste d'achats
- [ ] **Ameliorer la recherche** : recherche full-text PostgreSQL, filtres avances

### Priorite basse
- [ ] **Location de materiel** : integrer Kiloutou et Loxam (tarifs location)
- [ ] **Geolocalisation** : proposer les prix du magasin le plus proche de l'utilisateur
- [ ] **API publique** : pour integration par des pros du BTP
- [ ] **Monetisation** : liens affilies (quand approuve), publicite ciblee
- [ ] **PWA / App mobile** : version mobile optimisee

### Problemes connus
- DataDome bloque Leroy Merlin et Castorama (scraping direct impossible)
- Wurth : prix necessitent un compte B2B (pas de prix publics)
- Point P : login pro obligatoire pour voir les prix
- Site encore trop basique pour les plateformes d'affiliation (refus Awin)

---

## 12. Arborescence du projet

```
C:\Users\User\btp-comparateur\
|-- data/
|   |-- btp_comparateur.db          # SQLite locale (dev)
|   |-- bricodepot_stores.json      # 127 depots Brico Depot France
|
|-- db/
|   |-- models.py                   # SQLAlchemy models (Store, Product, StoreListing, PriceHistory, ScrapeRun)
|   |-- migrate_to_neon.py          # Script migration SQLite -> Neon PostgreSQL
|
|-- scrapers/
|   |-- items.py                    # BTPProductItem definition
|   |-- pipelines.py                # Validation + Normalisation + Database pipelines
|   |-- settings.py                 # Config Scrapy
|   |-- spiders/
|       |-- base.py                 # BaseBTPSpider (make_item, parse_price)
|       |-- brico_depot.py          # Sitemap HTTP, fonctionnel
|       |-- tollens.py              # HTTP categories, fonctionnel
|       |-- wurth.py                # Suggest API + categories, partiellement fonctionnel
|       |-- castorama.py            # Playwright, bloque DataDome
|       |-- leroy_merlin.py         # Googlebot UA, bloque DataDome
|       |-- bricorama.py            # Playwright headed, a tester
|       |-- bricomarche.py          # Playwright headed, a tester
|       |-- kiloutou.py             # Location materiel, a tester
|       |-- loxam.py                # Location materiel, a tester
|
|-- pipeline/
|   |-- spec_extractor.py           # Extraction specs depuis noms produits (30+ champs)
|   |-- matcher.py                  # Matching cross-enseigne (EAN/ref/fuzzy)
|   |-- normalizer.py               # Normalisation noms produits
|   |-- categorizer.py              # Auto-categorisation (37 categories)
|   |-- validator.py                # Rapport qualite donnees
|   |-- awin_feed.py                # Importeur flux CSV/XML Awin
|   |-- daily_run.py                # Pipeline quotidien complet
|
|-- web/
|   |-- app/                        # Next.js App Router
|   |   |-- page.tsx                # Accueil
|   |   |-- layout.tsx              # Layout global (meta SEO, CartProvider, CookieBanner)
|   |   |-- sitemap.ts              # Sitemap dynamique
|   |   |-- globals.css             # Styles globaux
|   |   |-- api/                    # Routes API (products, categories, search, autocomplete, stores)
|   |   |-- produit/[slug]/         # Fiche produit
|   |   |-- categories/[slug]/      # Page categorie
|   |   |-- recherche/              # Page recherche
|   |   |-- guides/[slug]/          # Articles guides
|   |   |-- magasins/               # Carte magasins
|   |   |-- faq/                    # FAQ
|   |   |-- a-propos/               # A propos
|   |   |-- contact/                # Contact
|   |   |-- panier/                 # Panier
|   |   |-- mentions-legales/       # Legal
|   |   |-- cgu/                    # CGU
|   |   |-- confidentialite/        # RGPD
|   |   |-- cookies/                # Politique cookies
|   |-- components/                 # Composants React (Navbar, Footer, SearchBar, ProductCard, PriceTable, PriceChart, FilterSidebar, Pagination, LogoCarousel, CookieBanner)
|   |-- lib/                        # Utilitaires (db.ts, cart-context.tsx)
```

---

*Document genere le 21 mars 2026. Ce fichier constitue la reference unique pour l'etat complet du projet BatiPrix.*
