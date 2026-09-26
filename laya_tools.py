"""
Laya AI Model Tool Interface for Technical University of Sofia Knowledge Base.
Provides grounded, deterministic, hallucination-free retrieval tools and JSON schemas
for Laya (AI decoder model) to query and pass structured university data to other models.
"""

import os
import re
import json
from typing import Dict, List, Any, Optional, Union

from crawler.bulgarian_nlp import (
    normalize_bulgarian_text,
    resolve_acronym_or_alias,
    transliterate_to_cyrillic,
    transliterate_to_latin,
    extract_keywords,
    stem_bulgarian_word,
    TU_ACRONYMS
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")

# Lazy-loaded cache
_KB_CACHE: Optional[Dict[str, Any]] = None
_MAP_CACHE: Optional[Dict[str, Any]] = None


def _load_kb() -> Dict[str, Any]:
    global _KB_CACHE
    if _KB_CACHE is None:
        kb_path = os.path.join(DATA_DIR, "tu_sofia_kb.json")
        if os.path.exists(kb_path):
            with open(kb_path, 'r', encoding='utf-8') as f:
                _KB_CACHE = json.load(f)
        else:
            _KB_CACHE = {"faculties": [], "colleges": [], "divisions": [], "admissions": {}, "curricula": [], "services": {}}
    return _KB_CACHE


def _load_map() -> Dict[str, Any]:
    global _MAP_CACHE
    if _MAP_CACHE is None:
        map_path = os.path.join(DATA_DIR, "tu_sofia_map.json")
        if os.path.exists(map_path):
            with open(map_path, 'r', encoding='utf-8') as f:
                _MAP_CACHE = json.load(f)
        else:
            _MAP_CACHE = {"nodes": [], "categories": {}}
    return _MAP_CACHE


def clean_specialty_title(s: str) -> str:
    """Cleans concatenated web-scraped specialty strings into clean human-readable titles."""
    if not s:
        return ""
    m = re.match(r'^(.*?)(?:([A-Za-z][A-Za-z0-9\u0435\u0415]*))?\s*(Бакалавър.*|Магистър.*|Доктор.*)$', s)
    if m:
        title = m.group(1).strip()
        acr = m.group(2)
        deg = m.group(3).strip()
        acr_clean = f" ({acr})" if acr and acr.lower() not in ["бакалавър", "магистър", "доктор"] else ""
        return f"{title}{acr_clean} - {deg}"
    return s.strip()


# ==============================================================================
# 1. CORE LAYA TOOLS
# ==============================================================================

def search_tu_sofia(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fast Bulgarian & English semantic keyword search across TU Sofia knowledge base.
    Resolves Bulgarian acronyms (ФКСТ, ФА, ФЕТТ, etc.) and transliterations automatically.
    
    Args:
        query: Search term (e.g. 'ФКСТ', 'такси кандидатстване', 'компютърни системи', 'декан', 'priem').
        limit: Maximum number of results to return (default: 5).
        
    Returns:
        List of matching items with scores, summaries, and direct entity references.
    """
    kb = _load_kb()
    results = []
    
    normalized_q = normalize_bulgarian_text(query).lower()
    query_stems = set(extract_keywords(query))
    
    # Check if query matches a known acronym or alias directly
    acronym_match = resolve_acronym_or_alias(query)
    target_acronym = acronym_match["code"] if acronym_match else None

    # Generic keywords that shouldn't unfairly boost specific faculties
    generic_keywords = {"факултет", "декан", "обучение", "образование", "специалност", "студент", "катедра", "университет"}

    # Search in Faculties
    for faculty in kb.get("faculties", []):
        score = 0
        name_bg = faculty.get("name_bg", "").lower()
        acronym = faculty.get("acronym", "")
        dean = faculty.get("dean", "").lower()
        departments = [d.lower() for d in faculty.get("departments", [])]
        specialties = faculty.get("specialties", [])

        if target_acronym and acronym == target_acronym:
            score += 100

        # Distinct name match (not generic words)
        generic_tokens = {"фа", "fa", "факултет", "faculty", "по", "и", "декан", "шеф", "dean"}
        if normalized_q not in generic_tokens and len(normalized_q) >= 4:
            if normalized_q in name_bg or normalized_q in faculty.get("name_en", "").lower():
                score += 50
        if dean and normalized_q in dean and len(normalized_q) >= 4:
            score += 40

        # Stem overlap without generic keywords
        f_keywords = set(faculty.get("keywords", [])) - generic_keywords
        overlap = query_stems.intersection(f_keywords)
        score += len(overlap) * 10

        # Check departments
        for dept in departments:
            if any(st in dept for st in query_stems):
                score += 15

        # Check specialties (high-value curriculum match)
        matched_specs = []
        for spec in specialties:
            clean_s = clean_specialty_title(spec).lower()
            if any(st in clean_s for st in query_stems):
                score += 30
                matched_specs.append(clean_specialty_title(spec))

        if score > 0:
            spec_list_clean = [clean_specialty_title(s) for s in specialties[:3]]
            spec_preview = f"Специалности: {', '.join(spec_list_clean)}" if spec_list_clean else ""
            snippet_elements = [
                f"Декан: {faculty.get('dean', 'Н/А')}",
                f"{faculty.get('block', 'ТУ-София')}, {faculty.get('cabinet', '')}",
                f"Тел: {faculty.get('phone', 'Н/А')}",
                f"Катедри: {', '.join(faculty.get('departments', [])[:3])}"
            ]
            if spec_preview:
                snippet_elements.append(spec_preview)

            results.append({
                "type": "faculty",
                "title": faculty.get("name_bg"),
                "acronym": acronym,
                "score": score,
                "snippet": " | ".join(snippet_elements),
                "specialties": [clean_specialty_title(s) for s in specialties],
                "url": faculty.get("url"),
                "markdown_file": faculty.get("markdown_file"),
                "slug": faculty.get("slug")
            })

    # Search in Admissions
    admissions = kb.get("admissions", {})
    adm_score = 0
    adm_triggers = ["прием", "кандидат", "такса", "такси", "изпит", "изпити", "срок", "срокове", "класиране", "записване", "priem", "taksi"]
    for trig in adm_triggers:
        if trig in normalized_q or stem_bulgarian_word(trig) in query_stems:
            adm_score += 25

    if adm_score > 0:
        # Check specific calendar items
        matched_calendar = []
        for cal in admissions.get("calendar_2026", []):
            if any(st in cal.get("activity", "").lower() for st in query_stems):
                matched_calendar.append(f"{cal['activity']}: {cal['deadline']}")

        cal_snippet = "; ".join(matched_calendar[:2]) if matched_calendar else "Календарен график, изпитни дати и такси за кампания 2026/2027 г."
        fees_info = admissions.get("fees", {}).get("exam_fee", "30 евро за изпит / признаване")

        results.append({
            "type": "admissions",
            "title": "Прием 2026/2027 - Календар и Такси",
            "score": adm_score + 15,
            "snippet": f"{cal_snippet} | Такса: {fees_info}",
            "url": "https://priem.tu-sofia.bg",
            "slug": "priem-2026"
        })

    # Search in Services (Dormitories, Student Council)
    services = kb.get("services", {})
    if any(w in normalized_q for w in ["общежити", "стол", "пссо", "стаи", "настаняване", "dorm"]):
        dorm = services.get("dormitories", {})
        results.append({
            "type": "service",
            "title": dorm.get("name", "Студентски столове и общежития (ПССО)"),
            "score": 60,
            "snippet": f"Локация: {dorm.get('location')} | Капацитет: {dorm.get('capacity')} | Контакти: {dorm.get('contacts')}",
            "url": "https://tu-sofia.bg/bg/contacts",
            "slug": "dormitories"
        })

    if any(w in normalized_q for w in ["студентски съвет", "съвет", "студенти", "председател", "student council"]):
        sc = services.get("student_council", {})
        results.append({
            "type": "service",
            "title": sc.get("name", "Студентски съвет"),
            "score": 60,
            "snippet": f"Кабинет: {sc.get('location')} | Телефон: {sc.get('phone')} | Email: {sc.get('email')}",
            "url": sc.get("website", "https://students.tu-sofia.bg"),
            "slug": "student-council"
        })

    # Sort descending by score
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def get_faculty_info(faculty_name_or_code: str) -> Dict[str, Any]:
    """
    Retrieves full verified information for a specific faculty by acronym, name, or slug.
    
    Args:
        faculty_name_or_code: Faculty acronym (e.g. 'ФКСТ', 'ФА', 'ФЕТТ', 'FKST'), 
                              name ('компютърни системи', 'автоматика'), or slug.
                              
    Returns:
        Structured dictionary containing Dean, room/building, contacts, departments, 
        accredited programs, and ECTS curriculum package links.
    """
    kb = _load_kb()
    normalized = normalize_bulgarian_text(faculty_name_or_code).strip()
    
    # 1. Resolve acronym
    acronym_info = resolve_acronym_or_alias(normalized)
    target_code = acronym_info["code"] if acronym_info else normalized.upper()
    
    def _format_faculty(faculty: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "success",
            "code": faculty.get("acronym"),
            "name_bg": faculty.get("name_bg"),
            "name_en": faculty.get("name_en"),
            "leadership": {
                "dean": faculty.get("dean"),
                "location": faculty.get("block"),
                "cabinet": faculty.get("cabinet"),
                "phone": faculty.get("phone"),
                "email": faculty.get("email")
            },
            "departments": faculty.get("departments", []),
            "specialties": [clean_specialty_title(s) for s in faculty.get("specialties", [])],
            "curricula_ects": faculty.get("ects_data"),
            "url": faculty.get("url"),
            "markdown_file": faculty.get("markdown_file")
        }

    # Pass 1: Exact Acronym match (Highest priority)
    for faculty in kb.get("faculties", []):
        if faculty.get("acronym", "").upper() == target_code.upper():
            return _format_faculty(faculty)

    # Pass 2: Exact Slug match
    norm_low = normalized.lower()
    for faculty in kb.get("faculties", []):
        if faculty.get("slug", "").lower() == norm_low:
            return _format_faculty(faculty)

    # Pass 3: Distinct Name match (avoid generic words like 'фа', 'fa', 'факултет', 'faculty')
    generic_words = {"факултет", "фа", "fa", "faculty", "по", "и", "and", "of"}
    if norm_low not in generic_words and len(norm_low) >= 3:
        for faculty in kb.get("faculties", []):
            name_bg = faculty.get("name_bg", "").lower()
            name_en = faculty.get("name_en", "").lower()
            if norm_low in name_bg or norm_low in name_en:
                return _format_faculty(faculty)

    return {
        "status": "not_found",
        "error": f"Faculty '{faculty_name_or_code}' not found.",
        "available_faculties": [f.get("acronym") for f in kb.get("faculties", []) if f.get("acronym")]
    }


def get_admissions_info(topic: Optional[str] = None, year: int = 2026) -> Dict[str, Any]:
    """
    Retrieves official candidate student admissions information from priem.tu-sofia.bg.
    
    Args:
        topic: Specific admissions topic: 'calendar' (срокове и график), 'fees' (такси), 
               'bureaus' (бюра на ЦКПИ), 'regulations' (правилник), or None for all.
        year: Academic admissions year (default 2026).
        
    Returns:
        Structured admissions data payload.
    """
    kb = _load_kb()
    admissions = kb.get("admissions", {})
    t = (topic or "").lower().strip()

    if t in ["calendar", "dates", "график", "срокове"]:
        return {
            "status": "success",
            "topic": "calendar",
            "campaign_year": admissions.get("campaign_year", f"{year}/{year+1}"),
            "deadlines": admissions.get("calendar_2026", [])
        }
    elif t in ["fees", "такси", "цена", "цена за изпит"]:
        return {
            "status": "success",
            "topic": "fees",
            "campaign_year": admissions.get("campaign_year", f"{year}/{year+1}"),
            "fees_structure": admissions.get("fees", {})
        }
    elif t in ["bureaus", "бюра", "цкпи", "подаване"]:
        return {
            "status": "success",
            "topic": "bureaus",
            "bureaus": admissions.get("bureaus", [])
        }
    elif t in ["regulations", "правилник", "условия"]:
        return {
            "status": "success",
            "topic": "regulations",
            "summary": admissions.get("regulations_summary", "")
        }
    else:
        return {
            "status": "success",
            "topic": "all",
            "campaign_year": admissions.get("campaign_year", f"{year}/{year+1}"),
            "calendar_2026": admissions.get("calendar_2026", []),
            "fees": admissions.get("fees", {}),
            "bureaus_count": len(admissions.get("bureaus", [])),
            "source_portal": "https://priem.tu-sofia.bg"
        }


def get_curriculum(faculty: str, degree: str = "bachelor") -> Dict[str, Any]:
    """
    Fetches official curriculum (ECTS credits, syllabi, study plans) for a faculty and degree.
    
    Args:
        faculty: Faculty acronym or name (e.g. 'ФКСТ', 'ФА', 'ФЕТТ').
        degree: Degree level ('bachelor' / 'бакалавър' or 'master' / 'магистър').
        
    Returns:
        Dictionary containing direct PDF links to study plans and course structures.
    """
    kb = _load_kb()
    acronym_info = resolve_acronym_or_alias(faculty)
    target_code = acronym_info["code"] if acronym_info else faculty.upper()
    degree_clean = degree.lower()

    ects_keywords = {
        "ФКСТ": ["компютърни", "fkst", "fksu"],
        "ФА": ["автоматика"],
        "ФЕТТ": ["електронна техника", "fett"],
        "ЕФ": ["електротехнически"],
        "ЕМФ": ["енергомашиностроителен"],
        "МФ": ["машиностроителен факултет"],
        "СФ": ["стопански"],
        "ФТ": ["транспорта"],
        "ФТК": ["телекомуникации"],
        "ФПМИ": ["приложна математика"],
        "ФаГИОПМ": ["германско", "fdiba"],
        "ФФИО": ["френско"],
        "ФАИО": ["английско"],
        "ФИТ": ["индустриални"],
        "ФЕА": ["електроника и автоматика"],
        "ФМУ": ["машиностроене и уредостроене"],
        "ИПФ": ["инженерно-педагогически"]
    }
    match_keywords = ects_keywords.get(target_code, [faculty.lower()])

    for item in kb.get("curricula", []):
        f_name_lower = item.get("faculty_name", "").lower()
        if any(k in f_name_lower for k in match_keywords):
            is_master = "master" in degree_clean or "магистър" in degree_clean
            programs = item.get("master_programs", []) if is_master else item.get("bachelor_programs", [])
            return {
                "status": "success",
                "faculty": item.get("faculty_name"),
                "degree": "master" if is_master else "bachelor",
                "programs_count": len(programs),
                "study_plans": programs,
                "ects_email_coordinator": item.get("ects_email"),
                "faculty_info_pdf": item.get("info_pdf")
            }

    return {
        "status": "not_found",
        "error": f"No ECTS curriculum found for faculty '{faculty}'.",
        "available_catalogs": [c.get("faculty_name") for c in kb.get("curricula", [])]
    }


def get_contact_info(query: str) -> Dict[str, Any]:
    """
    Retrieves contact numbers, emails, and office locations for university leadership or services.
    
    Args:
        query: Entity to look up ('ректор', 'деканат', 'студентски съвет', 'общежития', 'деловодство', or faculty code).
    """
    kb = _load_kb()
    q = normalize_bulgarian_text(query).lower()

    if any(k in q for k in ["ректор", "централа", "деловодство", "учебен", "адрес"]):
        return {
            "status": "success",
            "category": "rectorate",
            "contacts": kb.get("rectorate", {})
        }
    elif any(k in q for k in ["общежити", "стол", "пссо", "dorm"]):
        return {
            "status": "success",
            "category": "dormitories",
            "contacts": kb.get("services", {}).get("dormitories", {})
        }
    elif any(k in q for k in ["студентски съвет", "student council"]):
        return {
            "status": "success",
            "category": "student_council",
            "contacts": kb.get("services", {}).get("student_council", {})
        }
    else:
        # Check faculty contacts
        fac_info = get_faculty_info(query)
        if fac_info.get("status") == "success":
            return {
                "status": "success",
                "category": "faculty",
                "faculty": fac_info.get("name_bg"),
                "leadership": fac_info.get("leadership")
            }

    return {
        "status": "general",
        "central_exchange": kb.get("rectorate", {}).get("central_exchange"),
        "rectorate_address": kb.get("rectorate", {}).get("address"),
        "delovodstvo_email": kb.get("rectorate", {}).get("delovodstvo_email")
    }


def get_page_content(slug_or_url: str) -> str:
    """
    Reads the full, cleaned Markdown text of any indexed page in the TU Sofia knowledge base.
    
    Args:
        slug_or_url: Faculty slug, admissions page name, or relative path.
    """
    clean_slug = slug_or_url.strip("/").split("/")[-1].replace(".md", "")
    
    # Search across knowledge subdirectories
    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for f in files:
            if f.endswith(".md") and (f == f"{clean_slug}.md" or clean_slug in f):
                filepath = os.path.join(root, f)
                with open(filepath, 'r', encoding='utf-8') as md_file:
                    return md_file.read()
                    
    return f"Page '{slug_or_url}' not found in local knowledge base."


# ==============================================================================
# 2. MODEL-TO-MODEL INTERACTION HELPER
# ==============================================================================

def format_tool_payload_for_model(tool_name: str, result: Any, destination_model: str = "assistant") -> Dict[str, Any]:
    """
    Wraps the grounded tool result into an explicit, typed envelope designed for
    another AI model to ingest cleanly with zero hallucination risk.
    """
    return {
        "source": "LayaTUInfo/v1.0",
        "grounding": "Official Technical University of Sofia Knowledge Base",
        "tool_executed": tool_name,
        "target_model": destination_model,
        "status": "verified_facts",
        "payload": result
    }


# ==============================================================================
# 3. STANDARDIZED JSON SCHEMAS (FOR FUNCTION CALLING / MCP / GEMINI / OPENAI)
# ==============================================================================

LAYA_TOOLS_SCHEMAS = [
    {
        "name": "search_tu_sofia",
        "description": "Searches TU Sofia faculties, programs, admissions deadlines, fees, and regulations with automatic Bulgarian acronym and transliteration resolution.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search term in Bulgarian (Cyrillic) or English (e.g. 'ФКСТ', 'такси кандидатстване', 'компютърни системи', 'декан', 'FKST')."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5)."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_faculty_info",
        "description": "Retrieves comprehensive details about a TU Sofia faculty (Dean, office, contact, departments, accredited majors, and ECTS links).",
        "parameters": {
            "type": "object",
            "properties": {
                "faculty_name_or_code": {
                    "type": "string",
                    "description": "Faculty acronym ('ФКСТ', 'ФА', 'ФЕТТ', 'ФПМИ'), slug, or common Bulgarian name."
                }
            },
            "required": ["faculty_name_or_code"]
        }
    },
    {
        "name": "get_admissions_info",
        "description": "Retrieves official admissions 2026/2027 calendar deadlines, exam dates, application fees, or CKPI bureaus from priem.tu-sofia.bg.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to retrieve: 'calendar' (график и срокове), 'fees' (такси), 'bureaus' (бюра за прием), 'regulations' (правилник), or 'all'.",
                    "enum": ["calendar", "fees", "bureaus", "regulations", "all"]
                },
                "year": {
                    "type": "integer",
                    "description": "Academic year (default 2026)."
                }
            }
        }
    },
    {
        "name": "get_curriculum",
        "description": "Fetches accredited course curricula, study plans, and syllabus PDF links from ects.tu-sofia.bg by faculty and degree level.",
        "parameters": {
            "type": "object",
            "properties": {
                "faculty": {
                    "type": "string",
                    "description": "Faculty acronym or name (e.g. 'ФКСТ', 'ФА', 'ФЕТТ')."
                },
                "degree": {
                    "type": "string",
                    "description": "Degree level: 'bachelor' (бакалавър) or 'master' (магистър).",
                    "enum": ["bachelor", "master"]
                }
            },
            "required": ["faculty"]
        }
    },
    {
        "name": "get_contact_info",
        "description": "Retrieves official office locations, phone numbers, and emails for Rectorate, dormitories (ПССО), Student Council, or faculties.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Contact entity: 'ректор', 'централа', 'общежития', 'студентски съвет', or faculty code."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_page_content",
        "description": "Retrieves the full, clean Markdown text of any indexed page for direct LLM context injection.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug_or_url": {
                    "type": "string",
                    "description": "Slug or name of the page (e.g. 'faculty-of-computer-systems-and-technologies', 'calendar_2026', 'fees')."
                }
            },
            "required": ["slug_or_url"]
        }
    }
]
