"""Extract structured product specifications from product names and raw data."""
import re


# ─── COLOR LIST (French) ──────────────────────────────────
COLORS = [
    # Basics
    'blanc', 'noir', 'gris', 'rouge', 'bleu', 'vert', 'jaune', 'orange',
    'marron', 'beige', 'rose', 'violet', 'turquoise',
    # Construction-specific
    'anthracite', 'ardoise', 'ivoire', 'crème', 'taupe', 'sable',
    'pierre', 'terracotta', 'terre cuite', 'brique', 'rouille',
    'chocolat', 'cappuccino', 'lin', 'grège',
    # Wood tones
    'chêne', 'noyer', 'pin', 'hêtre', 'acajou', 'teck', 'wengé',
    'merisier', 'bouleau', 'érable', 'ébène',
    # Metals
    'chromé', 'doré', 'argenté', 'bronze', 'cuivré', 'nickel', 'inox',
    # Modifiers (compound)
    'gris clair', 'gris foncé', 'gris anthracite', 'gris perle',
    'bleu nuit', 'bleu canard', 'vert olive', 'vert sauge',
    'blanc cassé', 'blanc nacré', 'noir mat',
]
# Sort longest first so "gris anthracite" matches before "gris"
COLORS.sort(key=len, reverse=True)

# ─── FINISH LIST ──────────────────────────────────────────
FINISHES = [
    'satin', 'satinée', 'satiné',
    'mat', 'mate', 'matte',
    'brillant', 'brillante',
    'velours',
    'laqué', 'laquée',
    'brossé', 'brossée',
    'poli', 'polie',
    'brut', 'brute',
    'verni', 'vernie',
    'texturé', 'texturée',
    'monocouche',
    'bicouche',
]

# ─── MATERIAL LIST ────────────────────────────────────────
MATERIALS = [
    'inox', 'acier inoxydable',
    'acier galvanisé', 'acier zingué', 'acier',
    'galvanisé', 'zingué',
    'pvc', 'polyéthylène', 'polypropylène', 'abs',
    'cuivre', 'laiton', 'bronze',
    'aluminium', 'alu',
    'zinc',
    'fonte',
    'bois massif', 'bois',
    'plâtre', 'ba13', 'ba10', 'ba15',
    'béton', 'ciment', 'mortier',
    'grès cérame', 'grès', 'faïence', 'céramique', 'porcelaine',
    'verre trempé', 'verre',
    'fibre de verre',
    'polystyrène', 'laine de verre', 'laine de roche',
    'multicouche', 'per',
]
MATERIALS.sort(key=len, reverse=True)


def extract_specs(name: str, spider_specs: dict | None = None) -> dict:
    """Extract structured specifications from a product name.

    Args:
        name: Product name string
        spider_specs: Optional dict of specs already extracted by the spider
                      (from JSON-LD additionalProperty etc.)

    Returns:
        Dict with extracted specs. Spider specs take priority over name parsing.
    """
    specs: dict = {}
    name_lower = name.lower()

    # ─── Volume/contenance ────────────────────────────────
    vol = re.search(r'(\d+(?:[.,]\d+)?)\s*(L|l|ml|cl|litres?)\b', name)
    if vol:
        specs['volume'] = vol.group(0).strip()

    # ─── Poids ────────────────────────────────────────────
    wt = re.search(r'(\d+(?:[.,]\d+)?)\s*kg\b', name, re.IGNORECASE)
    if wt:
        specs['weight'] = wt.group(0).strip()
    if 'weight' not in specs:
        # Match grams: "500 g", "250 g" but not single digit "g" or "5G"
        wt2 = re.search(r'(\d{2,})\s*g\b', name)
        if wt2:
            specs['weight'] = wt2.group(0).strip()

    # ─── Dimensions (LxWxH or LxW) ───────────────────────
    dim = re.search(
        r'(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)(?:\s*[xX×]\s*(\d+(?:[.,]\d+)?))?\s*(mm|cm|m)?\b',
        name
    )
    if dim:
        specs['dimensions'] = dim.group(0).strip()

    # ─── Diamètre ─────────────────────────────────────────
    dia = re.search(r'[Øø]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)?', name)
    if dia:
        specs['diameter'] = dia.group(0).strip()

    # ─── Épaisseur ────────────────────────────────────────
    ep = re.search(r'[ée]p(?:aisseur)?\.?\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)', name, re.IGNORECASE)
    if ep:
        specs['thickness'] = ep.group(0).strip()

    # ─── Longueur ─────────────────────────────────────────
    lng = re.search(r'[Ll](?:ong(?:ueur)?)?\.?\s*(\d+(?:[.,]\d+)?)\s*(m|cm|mm)\b', name)
    if lng:
        specs['length'] = lng.group(0).strip()

    # ─── Puissance (V, W, kW) ─────────────────────────────
    pw = re.search(r'(?<![A-Za-z])(\d+)\s*(V|W|kW)\b', name)
    if pw:
        val = int(pw.group(1))
        # Filter out cable references (H07V = 7V) and nonsense values
        if val >= 10:
            specs['power'] = pw.group(0).strip()

    # ─── Ampérage batterie ────────────────────────────────
    ah = re.search(r'(\d+(?:[.,]\d+)?)\s*Ah\b', name)
    if ah:
        specs['battery'] = ah.group(0).strip()

    # ─── Pack/lot/conditionnement ─────────────────────────
    pack = re.search(
        r'(?:lot|pack|boîte|bte|sachet|seau|sac|carton|palette)\s*(?:de\s*)?[\d\s]+\d|'
        r'(\d[\d\s]*\d)\s*(?:pièces?|pi[eè]ces?|pcs|vis|chevilles|clous|unités?|rouleaux?|plaques?|tubes?|embouts?|douilles?|forets?|lames?|feuilles?)\b|'
        r'(\d+)\s*(?:pièces?|pi[eè]ces?|pcs|vis|chevilles|clous|unités?|rouleaux?|plaques?|tubes?|embouts?|douilles?|forets?|lames?|feuilles?)\b',
        name, re.IGNORECASE
    )
    if pack:
        specs['pack_size'] = pack.group(0).strip()

    # ─── Couleur ──────────────────────────────────────────
    for color in COLORS:
        # Use word boundary matching to avoid partial matches
        if re.search(r'\b' + re.escape(color) + r'\b', name_lower):
            specs['color'] = color
            break

    # ─── Finition ─────────────────────────────────────────
    for finish in FINISHES:
        if re.search(r'\b' + re.escape(finish) + r'\b', name_lower):
            # Normalize to base form
            base_finish = finish.rstrip('eé')
            if base_finish in ('satin', 'satinée', 'satiné'):
                base_finish = 'satin'
            elif base_finish in ('mat', 'mate', 'matte', 'matt'):
                base_finish = 'mat'
            elif base_finish in ('brillant', 'brillante', 'brillant'):
                base_finish = 'brillant'
            else:
                base_finish = finish
            specs['finish'] = base_finish
            break

    # ─── Matière ──────────────────────────────────────────
    for material in MATERIALS:
        if re.search(r'\b' + re.escape(material) + r'\b', name_lower):
            specs['material'] = material
            break

    # ─── Type d'embout (tournevis, embouts) ─────────────────
    bit = re.search(
        r'\b(PH[0-4]|PZ[0-4]|Torx\s*T?\d+|T\d{1,2}(?=\b)|SL\s*\d+|'
        r'6\s*pans?\s*\d+|BTR\s*\d+|hexagonal(?:e)?\s*\d+|'
        r'plat(?:e)?|cruciforme|phillips|pozidri[vx])\b',
        name, re.IGNORECASE
    )
    if bit:
        specs['bit_type'] = bit.group(0).strip()

    # ─── Type d'outil ────────────────────────────────────────
    tool_types = [
        ('sans fil', 'sans fil'), ('filaire', 'filaire'),
        ('à percussion', 'percussion'), ('percussion', 'percussion'),
        ('à cliquet', 'à cliquet'), ('cliquet', 'à cliquet'),
        ('pneumatique', 'pneumatique'), ('hydraulique', 'hydraulique'),
        ('sds-?plus', 'SDS-Plus'), ('sds-?max', 'SDS-Max'),
        ('brushless', 'brushless'),
    ]
    for pattern, label in tool_types:
        if re.search(r'\b' + pattern + r'\b', name_lower):
            specs['tool_type'] = label
            break

    # ─── Type de scie ────────────────────────────────────────
    saw_types = [
        ('scie sauteuse', 'sauteuse'), ('scie circulaire', 'circulaire'),
        ('scie sabre', 'sabre'), ('scie cloche', 'cloche'),
        ('scie à onglet', 'à onglet'), ('scie sur table', 'sur table'),
        ('scie à ruban', 'à ruban'), ('scie à métaux', 'à métaux'),
        ('scie égoïne', 'égoïne'), ('scie plongeante', 'plongeante'),
    ]
    for pattern, label in saw_types:
        if pattern in name_lower:
            specs['saw_type'] = label
            break

    # ─── Type de pince ───────────────────────────────────────
    plier_types = [
        ('pince coupante', 'coupante'), ('pince multiprise', 'multiprise'),
        ('pince à bec', 'bec long'), ('pince bec long', 'bec long'),
        ('pince à sertir', 'à sertir'), ('pince à dénuder', 'à dénuder'),
        ('pince étau', 'étau'), ('pince universelle', 'universelle'),
        ('pince à circlips', 'circlips'), ('pince multifonctions', 'multifonctions'),
    ]
    for pattern, label in plier_types:
        if pattern in name_lower:
            specs['plier_type'] = label
            break

    # ─── Type de foret ───────────────────────────────────────
    drill_types = [
        ('foret béton', 'béton'), ('foret bois', 'bois'),
        ('foret métal', 'métal'), ('foret multi', 'multi-matériaux'),
        ('foret sds', 'SDS'), ('foret à étage', 'à étage'),
        ('mèche bois', 'bois'), ('mèche béton', 'béton'),
        ('trépan', 'trépan'),
    ]
    for pattern, label in drill_types:
        if pattern in name_lower:
            specs['drill_type'] = label
            break

    # ─── Type de disque ──────────────────────────────────────
    disc_types = [
        ('disque diamant', 'diamant'), ('disque tronçonnage', 'tronçonnage'),
        ('disque à tronçonner', 'tronçonnage'), ('disque meulage', 'meulage'),
        ('disque à meuler', 'meulage'), ('disque à lamelles', 'lamelles'),
        ('disque abrasif', 'abrasif'),
    ]
    for pattern, label in disc_types:
        if pattern in name_lower:
            specs['disc_type'] = label
            break

    # ─── Grain (abrasif, papier de verre) ────────────────────
    grain = re.search(r'\b(?:grain|gr\.?)\s*(\d+)\b|P\s*(\d{2,4})\b', name, re.IGNORECASE)
    if grain:
        specs['grain'] = grain.group(0).strip()

    # ─── Couple (Nm) ─────────────────────────────────────────
    couple = re.search(r'(\d+(?:[.,]\d+)?)\s*N\.?m\b', name)
    if couple:
        specs['torque'] = couple.group(0).strip()

    # ─── Vitesse (tr/min, rpm) ───────────────────────────────
    speed = re.search(r'(\d[\d\s]*\d)\s*(?:tr/min|rpm|tours/min)\b', name, re.IGNORECASE)
    if speed:
        specs['speed'] = speed.group(0).strip()

    # ─── Capacité mandrin ────────────────────────────────────
    chuck = re.search(r'mandrin\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*mm', name_lower)
    if chuck:
        specs['chuck'] = chuck.group(0).strip()

    # ─── Taille clé ─────────────────────────────────────────
    key_size = re.search(
        r'(?:clé|cle|clés|douille)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(?:mm|")?',
        name_lower
    )
    if key_size:
        specs['key_size'] = key_size.group(0).strip()

    # ─── Empreinte douille (1/4, 3/8, 1/2) ───────────────────
    drive = re.search(r'\b(1/4|3/8|1/2|3/4)\s*["\u2033]?\b', name)
    if drive:
        specs['drive_size'] = drive.group(0).strip()

    # ─── Nombre de dents (scie, lame) ────────────────────────
    teeth = re.search(r'(\d+)\s*(?:dents|dts)\b', name_lower)
    if teeth:
        specs['teeth'] = teeth.group(0).strip()

    # ─── Charge max ──────────────────────────────────────────
    load = re.search(r'(?:charge|maxi?\.?)\s*(\d+)\s*kg', name_lower)
    if load:
        specs['max_load'] = load.group(0).strip()

    # ─── Nombre de marches (échelle, escabeau) ───────────────
    steps = re.search(r'(\d+)\s*(?:marches?|échelons?|barreaux?)', name_lower)
    if steps:
        specs['steps'] = steps.group(0).strip()

    # ─── Débit / Pression (compresseur, pompe) ───────────────
    pressure = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:bars?|PSI)\b', name, re.IGNORECASE)
    if pressure:
        specs['pressure'] = pressure.group(0).strip()

    # ─── Section câble (électricité) ─────────────────────────
    section = re.search(r'(\d+(?:[.,]\d+)?)\s*mm[²2]\b', name)
    if section:
        specs['section'] = section.group(0).strip()

    # ─── Ampérage (disjoncteur, prise) ───────────────────────
    amp = re.search(r'(\d+)\s*A\b', name)
    if amp and not ah:  # Don't confuse with Ah (battery)
        specs['amperage'] = amp.group(0).strip()

    # ─── IP (indice protection) ──────────────────────────────
    ip = re.search(r'\bIP\s*(\d{2})\b', name)
    if ip:
        specs['ip_rating'] = ip.group(0).strip()

    # ─── Merge with spider-provided specs (spider takes priority) ──
    if spider_specs:
        for key, value in spider_specs.items():
            if value:  # Only override if spider has a non-empty value
                specs[key] = value

    return specs


def specs_to_json(specs: dict) -> str | None:
    """Convert specs dict to JSON string for storage."""
    if not specs:
        return None
    import json
    return json.dumps(specs, ensure_ascii=False)
