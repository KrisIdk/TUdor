"""
Bulgarian NLP & Normalization Utility for Technical University of Sofia Knowledge Base.
Provides Cyrillic normalization, bidirectional transliteration (Bulgarian State Standard),
acronym expansion, and morphology/stemming heuristics for AI decoder models like Laya.
"""

import re
import unicodedata
from typing import List, Dict, Optional, Tuple

# Bulgarian State Transliteration Standard (Law on Transliteration)
CYR_TO_LAT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
    'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
    'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sht', 'ъ': 'a', 'ь': 'y',
    'ю': 'yu', 'я': 'ya',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ж': 'Zh',
    'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N',
    'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F',
    'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sht', 'Ъ': 'A', 'Ь': 'Y',
    'Ю': 'Yu', 'Я': 'Ya'
}

# Multi-char Latin representations ordered by length descending for reverse mapping
LAT_TO_CYR_RULES = [
    ('4', 'ч'), ('6', 'ш'),
    ('sht', 'щ'), ('Sht', 'Щ'), ('SHT', 'Щ'),
    ('zh', 'ж'), ('Zh', 'Ж'), ('ZH', 'Ж'),
    ('ch', 'ч'), ('Ch', 'Ч'), ('CH', 'Ч'),
    ('sh', 'ш'), ('Sh', 'Ш'), ('SH', 'Ш'),
    ('ts', 'ц'), ('Ts', 'Ц'), ('TS', 'Ц'),
    ('yu', 'ю'), ('Yu', 'Ю'), ('YU', 'Ю'),
    ('ya', 'я'), ('Ya', 'Я'), ('YA', 'Я'),
    ('iu', 'ю'), ('Iu', 'Ю'), ('IU', 'Ю'),
    ('ia', 'я'), ('Ia', 'Я'), ('IA', 'Я'),
    ('a', 'а'), ('b', 'б'), ('v', 'в'), ('w', 'в'), ('g', 'г'), ('d', 'д'),
    ('e', 'е'), ('z', 'з'), ('i', 'и'), ('y', 'й'), ('k', 'к'),
    ('l', 'л'), ('m', 'м'), ('n', 'н'), ('o', 'о'), ('p', 'п'),
    ('r', 'р'), ('s', 'с'), ('t', 'т'), ('u', 'у'), ('f', 'ф'),
    ('h', 'х'), ('c', 'ц'), ('j', 'ж'), ('q', 'я'),
    ('A', 'А'), ('B', 'Б'), ('V', 'В'), ('W', 'В'), ('G', 'Г'), ('D', 'Д'),
    ('E', 'Е'), ('Z', 'З'), ('I', 'И'), ('Y', 'Й'), ('K', 'К'),
    ('L', 'Л'), ('M', 'М'), ('N', 'Н'), ('O', 'О'), ('P', 'П'),
    ('R', 'Р'), ('S', 'С'), ('T', 'Т'), ('U', 'У'), ('F', 'Ф'),
    ('H', 'Х'), ('C', 'Ц'), ('J', 'Ж'), ('Q', 'Я')
]

# Comprehensive TU Sofia Acronyms, Aliases, and Full Titles
TU_ACRONYMS: Dict[str, Dict[str, Any]] = {
    "ФКСТ": {
        "full_bg": "Факултет по компютърни системи и технологии",
        "full_en": "Faculty of Computer Systems and Technologies",
        "aliases": [
            "фкст", "фксу", "fkst", "fksu", "кст", "kst", "компютърни системи",
            "компютърни системи и технологии", "компютърни", "компютри", "computer systems",
            "kompyutarni sistemi", "kompyutarni", "kompiutarni", "компютърния", "компютърният"
        ]
    },
    "ФА": {
        "full_bg": "Факултет по автоматика",
        "full_en": "Faculty of Automatics",
        "aliases": [
            "фа", "fa", "автоматика", "avtomatika", "автоматизация", "avtomatizacia",
            "avtomatizatsiya", "automatics", "automation", "автоматиката"
        ]
    },
    "ФЕТТ": {
        "full_bg": "Факултет по електронна техника и технологии",
        "full_en": "Faculty of Electronic Engineering and Technologies",
        "aliases": [
            "фетт", "fett", "електронна техника", "електроника", "електронен факултет",
            "electronics", "elektronika", "elektronna tehnika", "електронния", "електронният"
        ]
    },
    "ЕФ": {
        "full_bg": "Електротехнически факултет",
        "full_en": "Faculty of Electrical Engineering",
        "aliases": [
            "еф", "ef", "електротехника", "електротехнически", "електро", "електро факултет",
            "elektro", "elektrotehnika", "elektrotehnicheski", "electrical engineering",
            "електротехническия", "електротехническият", "elektrotehnicheskia"
        ]
    },
    "ЕМФ": {
        "full_bg": "Енергомашиностроителен факултет",
        "full_en": "Faculty of Power Engineering and Power Machines",
        "aliases": [
            "емф", "emf", "енергомашиностроителен", "енергетика", "топлоенергетика",
            "ядрена енергетика", "energetika"
        ]
    },
    "МФ": {
        "full_bg": "Машиностроителен факултет",
        "full_en": "Faculty of Mechanical Engineering",
        "aliases": [
            "мф", "мтф", "mf", "mtf", "машиностроителен", "машиностроителен факултет",
            "машиностроене", "механика", "mashinostroitelen", "mashinostroene", "mehanika",
            "mechanical engineering", "машиностроителния", "машиностроителният",
            "mashinostroitelnia", "mashinostroitelniya"
        ]
    },
    "ФИТ": {
        "full_bg": "Факултет по индустриални технологии",
        "full_en": "Faculty of Industrial Technology",
        "aliases": [
            "фит", "fit", "индустриални технологии", "индустриални", "industrial technologies",
            "industrialni", "материалознание"
        ]
    },
    "СФ": {
        "full_bg": "Стопански факултет",
        "full_en": "Faculty of Management",
        "aliases": [
            "сф", "sf", "стопански", "стопански факултет", "мениджмънт", "стопанско управление",
            "икономика", "management", "stopanski", "stopanski fakultet", "ikonomika",
            "стопанския", "стопанският", "stopanskia", "stopanskiya"
        ]
    },
    "ФТ": {
        "full_bg": "Факултет по транспорта",
        "full_en": "Faculty of Transport",
        "aliases": [
            "фт", "ft", "транспорт", "транспортен", "транспортен факултет", "авиация",
            "автомобилна техника", "transport", "transporten", "транспортния",
            "транспортният", "transportnia", "transportniya"
        ]
    },
    "ФТК": {
        "full_bg": "Факултет по телекомуникации",
        "full_en": "Faculty of Telecommunications",
        "aliases": [
            "фтк", "ftk", "ftc", "телекомуникации", "телеком", "съобщителна техника",
            "telecommunications", "telecom", "telekomunikacii", "telekomunikatsii"
        ]
    },
    "ФПМИ": {
        "full_bg": "Факултет по приложна математика и информатика",
        "full_en": "Faculty of Applied Mathematics and Informatics",
        "aliases": [
            "фпми", "fpmi", "фпм", "fpm", "фми", "fmi", "приложна математика",
            "информатика", "математика", "математика и информатика", "applied math",
            "applied mathematics", "matematika", "informatika", "prilozhna matematika"
        ]
    },
    "ФаГИОПМ": {
        "full_bg": "Факултет за германско инженерно обучение и промишлен мениджмънт (FDIBA)",
        "full_en": "Faculty of German Engineering Education and Industrial Management (FDIBA)",
        "aliases": [
            "фагиопм", "фгиопм", "fdiba", "фдиба", "немски факултет", "немски",
            "германски факултет", "германски", "nemski", "germanski"
        ]
    },
    "ФФИО": {
        "full_bg": "Факултет за френско инженерно обучение",
        "full_en": "French Faculty of Electrical Engineering",
        "aliases": ["ффио", "ffio", "френски факултет", "френски", "frenski"]
    },
    "ФАИО": {
        "full_bg": "Факултет за английско инженерно обучение",
        "full_en": "English Language Faculty of Engineering",
        "aliases": [
            "фаио", "faio", "английски факултет", "английски", "ае", "аео",
            "english faculty", "efe", "angliyski", "angliiski"
        ]
    },
    "ИСИГД": {
        "full_bg": "Интелигентни системи в индустрията, града и дома",
        "full_en": "Intelligent Systems in Industry, City and Home",
        "aliases": ["исигд", "isigd", "интелигентни системи", "исигд(ае)", "исигд ае", "интелигентни системи в индустрията"]
    },
    "Филиал Пловдив": {
        "full_bg": "Филиал Пловдив към ТУ-София",
        "full_en": "Technical University Sofia - Branch Plovdiv",
        "aliases": ["пловдив", "филиал пловдив", "ту пловдив", "plovdiv", "феа", "fea", "електроника и автоматика"]
    },
    "ИПФ Сливен": {
        "full_bg": "Инженерно-педагогически факултет - Сливен",
        "full_en": "Faculty of Engineering and Pedagogy - Sliven",
        "aliases": ["ипф сливен", "ипф", "ipf", "сливен", "ту сливен", "sliven"]
    },
    "ФМУ": {
        "full_bg": "Факултет по машиностроене и уредостроене - Пловдив",
        "full_en": "Faculty of Mechanical Engineering and Instrumentation - Plovdiv",
        "aliases": ["фму", "fmu", "машиностроене и уредостроене"]
    },
    "ТУЕС": {
        "full_bg": "Технологично училище „Електронни системи“",
        "full_en": "Technology School Electronic Systems (TUES)",
        "aliases": ["туес", "tues", "електронни системи училище"]
    },
    "ЦКПИ": {
        "full_bg": "Център за кандидатстудентска подготовка и информация",
        "full_en": "Center for Candidate Student Preparation and Information",
        "aliases": ["цкпи", "ckpi", "кандидатстудентски център", "бюро прием"]
    },
    "ЕТУС": {
        "full_bg": "Електронна университетска система (Е-Студент)",
        "full_en": "E-University Student Information System",
        "aliases": ["етус", "etus", "е-студент", "e-student", "e-university"]
    },
    "ECTS": {
        "full_bg": "Информационен пакет и учебни планове (ECTS)",
        "full_en": "European Credit Transfer and Accumulation System (ECTS)",
        "aliases": ["ects", "ектс", "учебни планове", "кредити", "curricula"]
    }
}

def normalize_bulgarian_text(text: str) -> str:
    """Normalizes Cyrillic text, standardizes quotes, hyphens, and whitespace."""
    if not text:
        return ""
    # Unicode NFC normalization
    normalized = unicodedata.normalize('NFC', text)
    # Standardize Bulgarian typography (quotations, dashes)
    normalized = re.sub(r'[\u201E\u201C\u201D"«»]', '"', normalized)
    normalized = re.sub(r'[\u2013\u2014\u2212]', '-', normalized)
    # Collapse multiple whitespaces
    normalized = re.sub(r'[ \t\r\f\v]+', ' ', normalized)
    return normalized.strip()


def transliterate_to_latin(text: str) -> str:
    """Transliterates Bulgarian Cyrillic text to Latin script according to Bulgarian Law."""
    result = []
    # Special Bulgarian law rule: "-ия" at the end of word -> "-ia"
    words = re.split(r'(\s+|[^\w\u0400-\u04FF])', text)
    for word in words:
        if re.search(r'[\u0400-\u04FF]', word):
            w_mod = re.sub(r'ия$', 'ia', word, flags=re.IGNORECASE)
            w_trans = "".join(CYR_TO_LAT.get(ch, ch) for ch in w_mod)
            result.append(w_trans)
        else:
            result.append(word)
    return "".join(result)


def transliterate_to_cyrillic(text: str) -> str:
    """Approximate transliteration of Latin Bulgarian slugs/terms back to Cyrillic."""
    res = text
    for lat, cyr in LAT_TO_CYR_RULES:
        res = res.replace(lat, cyr)
    return res


# Inverted index for alias lookup
ALIAS_TO_CANONICAL: Dict[str, str] = {}
for code, data in TU_ACRONYMS.items():
    ALIAS_TO_CANONICAL[code.lower()] = code
    ALIAS_TO_CANONICAL[data["full_bg"].lower()] = code
    for alias in data["aliases"]:
        a_low = alias.lower()
        ALIAS_TO_CANONICAL[a_low] = code
        # Transliterated Latin form
        a_lat = transliterate_to_latin(a_low).lower()
        ALIAS_TO_CANONICAL[a_lat] = code
        # Transliterated Cyrillic form
        a_cyr = transliterate_to_cyrillic(a_low).lower()
        ALIAS_TO_CANONICAL[a_cyr] = code

# Precomputed sorted aliases by length descending for greedy phrase matching
SORTED_ALIASES_DESC = sorted(ALIAS_TO_CANONICAL.keys(), key=lambda x: len(x), reverse=True)


def stem_bulgarian_word(word: str) -> str:
    """
    Lightweight suffix stripper for Bulgarian nominal/adjectival inflection.
    Removes definite articles (-ият, -ят, -ът, -ия, -та, -то, -те, -а, -я) and common plural endings.
    """
    w = word.lower()
    if len(w) <= 3:
        return w
    
    # Strip definite articles
    for suffix in ['ият', 'ят', 'ът', 'ия', 'та', 'то', 'те', 'а', 'я']:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[:-len(suffix)]
            break
            
    # Strip common plural suffixes
    for suffix in ['ове', 'еве', 'ци', 'и']:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[:-len(suffix)]
            break
            
    return w


def resolve_acronym_or_alias(query: str) -> Optional[Dict[str, Any]]:
    """
    Resolves any acronym, abbreviation, faculty alias, or shlokavica query to its canonical entity.
    Supports full queries (e.g. 'koi e dekan na fa', 'кой е декан на ФКСТ', 'dekan na mashinostroitelnia').
    """
    cleaned = normalize_bulgarian_text(query).lower()
    cyr_cleaned = transliterate_to_cyrillic(cleaned).lower()
    
    # 1. Direct match on whole query string
    if cleaned in ALIAS_TO_CANONICAL:
        code = ALIAS_TO_CANONICAL[cleaned]
        info = TU_ACRONYMS[code].copy()
        info["code"] = code
        return info
    if cyr_cleaned in ALIAS_TO_CANONICAL:
        code = ALIAS_TO_CANONICAL[cyr_cleaned]
        info = TU_ACRONYMS[code].copy()
        info["code"] = code
        return info

    # 2. Greedy phrase matching (longest alias first, min length 3)
    # Using word boundaries to avoid matching substrings like "фа" inside "факултет"
    for alias in SORTED_ALIASES_DESC:
        if len(alias) <= 2:
            continue
        pattern = r'(?<![a-zA-Zа-яА-Я0-9])' + re.escape(alias) + r'(?![a-zA-Zа-яА-Я0-9])'
        if re.search(pattern, cleaned) or re.search(pattern, cyr_cleaned):
            code = ALIAS_TO_CANONICAL[alias]
            info = TU_ACRONYMS[code].copy()
            info["code"] = code
            return info

    # 3. Discrete short token matching (for 2-char acronyms like 'фа', 'fa', 'ef', 'еф', 'mf', 'мф')
    tokens = re.findall(r'[a-zA-Zа-яА-Я0-9]+', cleaned)
    tokens_cyr = re.findall(r'[a-zA-Zа-яА-Я0-9]+', cyr_cleaned)
    for tok in tokens + tokens_cyr:
        if tok in ALIAS_TO_CANONICAL:
            code = ALIAS_TO_CANONICAL[tok]
            info = TU_ACRONYMS[code].copy()
            info["code"] = code
            return info
            
    return None


def extract_keywords(text: str) -> List[str]:
    """Tokenizes and stems Bulgarian text for inverted index searching with shlokavica support."""
    cleaned = normalize_bulgarian_text(text).lower()
    cyr_cleaned = transliterate_to_cyrillic(cleaned).lower()
    
    tokens = re.findall(r'[a-zA-Z\u0400-\u04FF0-9]+', cleaned)
    tokens_cyr = re.findall(r'[\u0400-\u04FF0-9]+', cyr_cleaned)
    
    all_tokens = list(set(tokens + tokens_cyr))
    
    # Common Bulgarian and Latin stop words
    stop_words = {
        'и', 'в', 'във', 'на', 'за', 'с', 'със', 'от', 'до', 'по', 'че', 'да', 'не',
        'се', 'си', 'е', 'са', 'беше', 'като', 'към', 'или', 'а', 'но', 'при', 'през',
        'още', 'вече', 'само', 'тук', 'там', 'всички', 'всичко', 'този', 'тази', 'това',
        'koi', 'koq', 'koe', 'kak', 'koga', 'zashto', 'na', 'za', 'ot', 'do', 'po', 'da', 'ne', 'se', 'si'
    }
    return [stem_bulgarian_word(t) for t in all_tokens if t not in stop_words and len(t) > 1]

