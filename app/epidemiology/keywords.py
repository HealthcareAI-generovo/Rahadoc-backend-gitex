"""
Disease keyword dictionary for epidemiological surveillance.

Maps canonical disease categories to French keyword patterns
used for matching against free-text Consultation.diagnostic fields.
"""

# Disease category -> list of keywords to match via SQL ILIKE
# Keywords are lowercase; matching is case-insensitive
DISEASE_KEYWORDS: dict[str, list[str]] = {
    "Grippe": [
        "grippe",
        "syndrome grippal",
        "influenza",
        "etat grippal",
        "état grippal",
    ],
    "Gastro-entérite": [
        "gastroentérite",
        "gastroenterite",
        "gastro-entérite",
        "gastro-enterite",
        "diarrhée aiguë",
        "diarrhee aigue",
    ],
    "Intoxication alimentaire": [
        "intoxication alimentaire",
        "toxi-infection",
        "tiac",
    ],
    "Angine": [
        "angine",
        "pharyngite",
        "amygdalite",
    ],
    "Bronchite": [
        "bronchite",
        "bronchiolite",
        "infection bronchique",
    ],
    "Pneumonie": [
        "pneumonie",
        "pneumopathie",
    ],
    "Conjonctivite": [
        "conjonctivite",
    ],
    "Rougeole": [
        "rougeole",
    ],
    "Varicelle": [
        "varicelle",
    ],
    "COVID-19": [
        "covid",
        "sars-cov",
        "coronavirus",
    ],
    "Tuberculose": [
        "tuberculose",
        "tbc",
        "bk positif",
    ],
    "Hépatite A": [
        "hepatite a",
        "hépatite a",
        "hepatite virale a",
        "hépatite virale a",
    ],
    "Méningite": [
        "meningite",
        "méningite",
    ],
    "Coqueluche": [
        "coqueluche",
    ],
    "Dengue": [
        "dengue",
    ],
}


def get_keyword_patterns() -> list[tuple[str, str]]:
    """
    Flatten DISEASE_KEYWORDS into (category, sql_pattern) pairs.

    Returns:
        List of tuples like ("Grippe", "%grippe%") for use in SQL ILIKE.
    """
    patterns = []
    for category, keywords in DISEASE_KEYWORDS.items():
        for keyword in keywords:
            patterns.append((category, f"%{keyword}%"))
    return patterns
