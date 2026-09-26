"""
Lightweight REST API & Web Server for Laya TU Sofia Explorer.
Coordinates Laya (the AI semantic decoder/retriever) with ТУдор (gemma4:e2b, the conversational speaker)
to provide a grounded, hallucination-free AI assistant for TU Sofia.
"""

import os
import sys
import json
import time
import traceback
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import httpx

# Ensure standard streams are UTF-8 compliant on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add root directory to sys.path so laya_tools can be imported cleanly
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from laya_tools import (
    search_tu_sofia,
    get_faculty_info,
    get_admissions_info,
    get_curriculum,
    get_contact_info,
    get_page_content,
    format_tool_payload_for_model,
    LAYA_TOOLS_SCHEMAS,
    clean_specialty_title,
    _load_kb,
    _load_map
)
from crawler.bulgarian_nlp import resolve_acronym_or_alias, normalize_bulgarian_text, transliterate_to_cyrillic

APP_DIR = os.path.dirname(__file__)
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
GEMMA_MODEL = "gemma4:e2b"
BOT_NAME = "ТУдор"


def detect_query_intent(query: str) -> str:
    """
    Classifies user inquiry into a focused intent to prevent data dumping
    and allow Laya to select only the relevant information.
    """
    normalized_q = normalize_bulgarian_text(query).lower()
    cyr_q = transliterate_to_cyrillic(normalized_q).lower()
    q_tokens = normalized_q.split() + cyr_q.split()

    # 1. Fee / Tuition / State quota / Cost
    fee_triggers = [
        "такса", "такси", "цена", "цени", "пари", "струва", "струват",
        "семестър", "семестриалн", "държавна поръчка", "платено",
        "плаща", "плащане", "fee", "cost", "taksi", "taksa", "kolko pari", "колко пари"
    ]
    if any(t in normalized_q or t in cyr_q for t in fee_triggers):
        return "FEE"

    # 2. Contact details (phone number, email, cabinet, GSM)
    contact_triggers = [
        "номер", "номера", "номерът", "nomer", "nomera", "nomerat",
        "телефон", "телефона", "телефонен", "телефонния", "telefon", "telefona", "telefonen", "telefonniq",
        "тел", "tel", "контакт", "контакти", "kontakt", "kontakti",
        "връзка", "vruzka", "имейл", "мейл", "email", "mail",
        "кабинет", "kabinet", "стая", "staya", "gsm", "гсм"
    ]
    is_contact = any(t in normalized_q or t in cyr_q or t in q_tokens for t in contact_triggers)

    # 3. Dean / Leadership
    dean_triggers = [
        "декан", "декана", "деканът", "шеф", "шефа", "директор", "ръководител", "кой ръководи",
        "dekan", "dekana", "shef", "shefa", "dean"
    ]
    is_dean = any(t in normalized_q or t in cyr_q or t in q_tokens for t in dean_triggers)

    if is_contact and is_dean:
        return "LEADERSHIP_CONTACT"

    if is_dean:
        return "LEADERSHIP"

    # 4. Faculty affiliation: where is a specialty taught / which faculty manages it
    where_triggers = [
        "кой факултет", "в кой факултет", "към кой факултет", "към кой",
        "къде се учи", "къде се преподава", "koi fakultet", "v koi fakultet", "kym koi"
    ]
    if any(t in normalized_q or t in cyr_q for t in where_triggers):
        return "FACULTY_AFFILIATION"

    # 5. Curriculum / What is studied / Subjects / Plan
    curr_triggers = [
        "какво се учи", "какво изучават", "какво представлява",
        "предмети", "дисциплини", "учебен план", "програма", "профил",
        "curriculum", "kakvo se uchi"
    ]
    if any(t in normalized_q or t in cyr_q for t in curr_triggers):
        return "CURRICULUM"

    # 6. List of specialties for a faculty
    specs_list_triggers = [
        "какви специалности", "кои специалности", "списък специалности",
        "специалности във", "специалности на", "какво мога да уча"
    ]
    if any(t in normalized_q or t in cyr_q for t in specs_list_triggers):
        return "FACULTY_SPECIALTIES"

    # 7. Calendar / Admissions dates / Deadlines
    cal_triggers = [
        "график", "срок", "срокове", "кога", "дата", "дати",
        "прием", "изпит", "изпити", "calendar", "priem", "koga"
    ]
    if any(t in normalized_q or t in cyr_q for t in cal_triggers):
        return "CALENDAR"

    # 8. Dormitories / Living / Campus services
    dorm_triggers = [
        "общежити", "стол", "пссо", "стаи", "настаняване",
        "dorm", "obshtejiti"
    ]
    if any(t in normalized_q or t in cyr_q for t in dorm_triggers):
        return "DORMITORY"

    # 9. Rectorate
    rector_triggers = [
        "ректор", "централа", "деловодство", "учебен отдел", "rektor"
    ]
    if any(t in normalized_q or t in cyr_q for t in rector_triggers):
        return "RECTORATE"

    if is_contact:
        return "CONTACTS"

    return "GENERAL"


def call_laya_retrieval(query: str):
    """
    Step 1: Laya decodes user intent, identifies entities, and SELECTS only the
    exact, relevant facts required to answer the query without overwhelming data dumps.
    """
    normalized_q = normalize_bulgarian_text(query).lower()
    cyr_q = transliterate_to_cyrillic(normalized_q).lower()
    intent = detect_query_intent(query)
    facts = {"intent": intent}
    reasoning = []

    # 1. Check for specific specialties
    is_isigd = (
        any(k in normalized_q or k in cyr_q for k in ["исигд", "isigd", "sich", "сих", "исидг", "isidg"])
        or (
            ("интелигент" in normalized_q or "inteligent" in normalized_q or "интелигент" in cyr_q)
            and ("систем" in normalized_q or "sistem" in normalized_q or "систем" in cyr_q)
        )
    )
    is_iti = (
        any(k in normalized_q or k in cyr_q for k in ["ити", "iti"])
        or (
            ("интелигент" in normalized_q or "inteligent" in normalized_q or "интелигент" in cyr_q)
            and ("технолог" in normalized_q or "tehnolog" in normalized_q or "технолог" in cyr_q)
        )
    )

    specialty_data = None
    if is_isigd:
        specialty_data = {
            "name": "Интелигентни системи в индустрията, града и дома (ИСИГД / SICH)",
            "primary_faculty": "Факултет по автоматика (ФА)",
            "english_module": "Специализирано обучение на английски език (SICHe) към ФА и ФАИО",
            "degree": "Бакалавър (редовно обучение - 4 години)",
            "semester_fee": "600 лв. (300 евро) на семестър",
            "quota": "Държавна поръчка (субсидирано обучение съгласно ЗВО)",
            "qualification": "Инженер по автоматика (ПН 5.2 Електротехника, електроника и автоматика)",
            "description": "Интердисциплинарна инженерна специалност в областта на IoT (интернет на нещата), изкуствен интелект, микроконтролери (ESP32, STM32, FPGA), роботизирани системи и автоматизация на умни домове и сгради."
        }
    elif is_iti:
        specialty_data = {
            "name": "Интелигентни технологии в индустрията (ИТИ / ITI)",
            "primary_faculty": "Факултет по компютърни системи и технологии (ФКСТ)",
            "english_module": "Обучение по софтуерни и компютърни технологии в индустрията",
            "degree": "Бакалавър (редовно обучение - 4 години)",
            "semester_fee": "550 лв. на семестър",
            "quota": "Държавна поръчка",
            "qualification": "Инженер по компютърни системи и технологии",
            "description": "Специалност към ФКСТ, насочена към софтуерните решения и компютърните технологии в съвременното индустриално производство."
        }

    # 2. Check for faculty
    acronym_info = resolve_acronym_or_alias(query)
    fac_info = None
    if acronym_info:
        code = acronym_info["code"]
        res = get_faculty_info(code)
        if res.get("status") == "success":
            fac_info = res

    # 3. LAYA SELECTS ONLY THE RELEVANT FACTS BASED ON INTENT
    if intent == "FEE":
        if specialty_data:
            facts["specialty_fee"] = {
                "specialty_name": specialty_data["name"],
                "primary_faculty": specialty_data["primary_faculty"],
                "degree": specialty_data["degree"],
                "semester_fee": specialty_data["semester_fee"],
                "quota": specialty_data["quota"],
                "language_module": "Таксата от 600 лв. (300 евро) важи както за обучението на български, така и за модула на английски език (SICHe към ФА/ФАИО)." if is_isigd else ""
            }
            reasoning.append(f"Laya подбра само ключовите данни за таксата на {specialty_data['name']}: {specialty_data['semester_fee']} по държавна поръчка.")
        else:
            facts["general_fees"] = {
                "application_fee": "30 евро (60 лв.) за явяване на кандидатстудентски изпит или признаване на матура",
                "standard_engineering_fee": "350 - 550 лв. на семестър за общите инженерни специалности по държавна поръчка",
                "sich_fee": "600 лв. (300 евро) на семестър за специалност ИСИГД / SICH",
                "foreign_language_fee": "600 - 800 лв. на семестър за чуждоезиковите програми (ФАИО, ФаГИОПМ, ФФИО)",
                "preliminary_exam_rule": "Кандидатите, ползващи предварителни изпити, подават документи без доплащане."
            }
            reasoning.append("Laya подбра синтезирана справка за семестриалните такси по държавна поръчка в ТУ-София.")

    elif intent == "FACULTY_AFFILIATION":
        if specialty_data:
            facts["specialty_faculty"] = {
                "specialty_name": specialty_data["name"],
                "primary_faculty": specialty_data["primary_faculty"],
                "english_module": specialty_data.get("english_module", ""),
                "degree": specialty_data["degree"]
            }
            reasoning.append(f"Laya отчете фокус 'Факултетна принадлежност': Специалността е към {specialty_data['primary_faculty']}.")
        elif fac_info:
            lead = fac_info.get("leadership", {})
            facts["faculty_overview"] = {
                "name": fac_info.get("name_bg"),
                "code": fac_info.get("code"),
                "dean": lead.get("dean"),
                "location": lead.get("location")
            }
            reasoning.append(f"Laya извлече информация за {fac_info.get('name_bg')}.")

    elif intent == "LEADERSHIP_CONTACT":
        if fac_info:
            lead = fac_info.get("leadership", {})
            phone_triggers = ["номер", "номера", "номерът", "nomer", "nomera", "nomerat", "телефон", "телефона", "telefon", "telefona", "тел", "tel", "gsm", "гсм"]
            email_triggers = ["имейл", "мейл", "email", "mail"]
            cabinet_triggers = ["кабинет", "kabinet", "стая", "staya", "къде", "kade", "локация"]

            if any(t in normalized_q or t in cyr_q for t in email_triggers):
                req_type = "email"
            elif any(t in normalized_q or t in cyr_q for t in cabinet_triggers):
                req_type = "cabinet"
            elif any(t in normalized_q or t in cyr_q for t in phone_triggers):
                req_type = "phone"
            else:
                req_type = "all"

            facts["leadership_contact"] = {
                "faculty": f"{fac_info.get('name_bg')} ({fac_info.get('code')})",
                "dean": lead.get("dean") or "Н/А",
                "phone": lead.get("phone") or "02 965 3417",
                "email": lead.get("email") or "",
                "cabinet": lead.get("cabinet") or "Н/А",
                "location": lead.get("location") or "Кампус ТУ-София",
                "target_type": req_type
            }
            if req_type == "phone":
                reasoning.append(f"Laya разпозна питане за телефонен номер на декана на {fac_info.get('code')}: {lead.get('phone')}.")
            elif req_type == "email":
                reasoning.append(f"Laya разпозна питане за email на декана на {fac_info.get('code')}: {lead.get('email')}.")
            elif req_type == "cabinet":
                reasoning.append(f"Laya разпозна питане за кабинет на декана на {fac_info.get('code')}: каб. {lead.get('cabinet')}.")
            else:
                reasoning.append(f"Laya подбра контактите на декана на {fac_info.get('code')}.")
        else:
            kb = _load_kb()
            examples = [{"code": f.get("acronym"), "name": f.get("name_bg"), "dean": f.get("dean"), "phone": f.get("phone")} for f in kb.get("faculties", [])[:4]]
            facts["faculty_disambiguation"] = {
                "total_faculties": len(kb.get("faculties", [])),
                "message": "В ТУ-София има 17 факултета. За кой факултет търсите телефон на декана?",
                "examples": examples
            }
            reasoning.append("Laya засече питане за телефон/контакт на декан без посочен факултет.")

    elif intent == "LEADERSHIP":
        if fac_info:
            lead = fac_info.get("leadership", {})
            facts["dean_info"] = {
                "faculty": f"{fac_info.get('name_bg')} ({fac_info.get('code')})",
                "dean": lead.get("dean", "Н/А"),
                "cabinet": lead.get("cabinet", "Н/А"),
                "location": lead.get("location", ""),
                "phone": lead.get("phone", ""),
                "email": lead.get("email", "")
            }
            reasoning.append(f"Laya подбра само данните за декана на {fac_info.get('code')}: {lead.get('dean')}.")
        else:
            kb = _load_kb()
            examples = [{"code": f.get("acronym"), "name": f.get("name_bg"), "dean": f.get("dean")} for f in kb.get("faculties", [])[:4]]
            facts["faculty_disambiguation"] = {
                "total_faculties": len(kb.get("faculties", [])),
                "message": "В ТУ-София има 17 факултета и филиала, като всеки има собствен декан.",
                "examples": examples
            }
            reasoning.append("Laya отчете запитване за декан без посочен факултет (17 факултета с отделни декани).")

    elif intent == "CURRICULUM":
        if specialty_data:
            facts["curriculum_info"] = {
                "specialty_name": specialty_data["name"],
                "primary_faculty": specialty_data["primary_faculty"],
                "focus_areas": specialty_data["description"],
                "degree": specialty_data["degree"]
            }
            reasoning.append(f"Laya подбра учебния фокус на {specialty_data['name']}.")
        elif fac_info:
            specs = [clean_specialty_title(s) for s in fac_info.get("specialties", [])[:6]]
            facts["faculty_specialties"] = {
                "faculty": fac_info.get("name_bg"),
                "specialties": specs
            }
            reasoning.append(f"Laya подбра специалностите към {fac_info.get('name_bg')}.")

    elif intent == "FACULTY_SPECIALTIES":
        if fac_info:
            specs = [clean_specialty_title(s) for s in fac_info.get("specialties", [])]
            facts["faculty_specialties"] = {
                "faculty": f"{fac_info.get('name_bg')} ({fac_info.get('code')})",
                "specialties": specs
            }
            reasoning.append(f"Laya извлече списък със специалности на {fac_info.get('code')}.")

    elif intent == "CALENDAR":
        cal = get_admissions_info(topic="calendar")
        deadlines = cal.get("deadlines", [])[:3]
        facts["admissions_calendar"] = {"key_deadlines": deadlines}
        reasoning.append(f"Laya подбра основните {len(deadlines)} календарни дати за кандидатстване.")

    elif intent == "DORMITORY":
        dorm = get_contact_info("общежития")
        facts["dormitories"] = dorm
        reasoning.append("Laya подбра контакти и локация на общежитията (ПССО).")

    elif intent == "RECTORATE":
        rectorate = get_contact_info("ректор")
        facts["rectorate"] = rectorate
        reasoning.append("Laya подбра контакти на Ректората (проф. Георги Венков, бул. Климент Охридски 8).")

    else:  # GENERAL
        if specialty_data:
            facts["specialty_summary"] = {
                "name": specialty_data["name"],
                "primary_faculty": specialty_data["primary_faculty"],
                "focus": specialty_data["description"],
                "degree": specialty_data["degree"],
                "semester_fee": specialty_data["semester_fee"]
            }
            reasoning.append(f"Laya подбра кратък синтез за {specialty_data['name']}.")
        elif fac_info:
            lead = fac_info.get("leadership", {})
            specs = [clean_specialty_title(s) for s in fac_info.get("specialties", [])[:4]]
            facts["faculty_summary"] = {
                "name": fac_info.get("name_bg"),
                "code": fac_info.get("code"),
                "dean": lead.get("dean"),
                "specialties_preview": specs
            }
            reasoning.append(f"Laya подбра кратък синтез за факултет {fac_info.get('code')}.")
        else:
            search_results = search_tu_sofia(query, limit=2)
            if search_results:
                facts["top_matches"] = search_results
                reasoning.append("Laya откри релевантна информация в семантичния граф.")
            else:
                reasoning.append("Laya прегледа запитването в семантичния граф на ТУ-София.")

    return facts, " | ".join(reasoning)


def prepare_facts_for_gemma(grounded_facts: dict, user_message: str = "") -> str:
    """
    Builds a concise, high-density factual prompt containing ONLY the selected
    facts so ТУдор (gemma4:e2b) evaluates the context in seconds and answers directly.
    """
    parts = []

    # 1. Specialty Fee
    if "specialty_fee" in grounded_facts:
        sf = grounded_facts["specialty_fee"]
        parts.append(
            f"ФОКУС: Семестриална такса за специалност\n"
            f"- Специалност: {sf.get('specialty_name')}\n"
            f"- Факултет: {sf.get('primary_faculty')}\n"
            f"- ОКС: {sf.get('degree')}\n"
            f"- СЕМЕСТРИАЛНА ТАКСА: {sf.get('semester_fee')}\n"
            f"- Статут: {sf.get('quota')}\n"
            f"- Езиков модул: {sf.get('language_module')}"
        )

    # 2. General Fees
    elif "general_fees" in grounded_facts:
        gf = grounded_facts["general_fees"]
        parts.append(
            f"ФОКУС: Семестриални такси по държавна поръчка в ТУ-София\n"
            f"- Общи инженерни специалности: {gf.get('standard_engineering_fee')}\n"
            f"- Специалност ИСИГД / SICH: {gf.get('sich_fee')}\n"
            f"- Чуждоезиково обучение: {gf.get('foreign_language_fee')}\n"
            f"- Изпитна такса кандидатстване: {gf.get('application_fee')}"
        )

    # 3. Specialty Faculty Affiliation
    if "specialty_faculty" in grounded_facts:
        sfac = grounded_facts["specialty_faculty"]
        parts.append(
            f"ФОКУС: Факултетна принадлежност на специалност\n"
            f"- Специалност: {sfac.get('specialty_name')}\n"
            f"- ОСНОВЕН ФАКУЛТЕТ: {sfac.get('primary_faculty')}\n"
            f"- Англоезичен модул: {sfac.get('english_module')}"
        )

    # 4. Dean / Leadership Contact & Info
    if "leadership_contact" in grounded_facts:
        lc = grounded_facts["leadership_contact"]
        target = lc.get("target_type", "all")
        if target == "phone":
            parts.append(
                f"ФОКУС: Телефонен номер на декана (потребителят търси номер/телефон)\n"
                f"- Факултет: {lc.get('faculty')}\n"
                f"- Декан: {lc.get('dean')}\n"
                f"- ТОЧЕН ТЕЛЕФОНЕН НОМЕР НА ДЕКАНА: {lc.get('phone')}\n"
                f"- ЗАДЪЛЖИТЕЛНО: Започни отговора директно с телефонния номер ({lc.get('phone')})!"
            )
        elif target == "email":
            parts.append(
                f"ФОКУС: Имейл адрес на декана\n"
                f"- Факултет: {lc.get('faculty')}\n"
                f"- Декан: {lc.get('dean')}\n"
                f"- ТОЧЕН ИМЕЙЛ НА ДЕКАНА: {lc.get('email')}\n"
                f"- ЗАДЪЛЖИТЕЛНО: Посочи директно имейл адреса!"
            )
        elif target == "cabinet":
            parts.append(
                f"ФОКУС: Кабинет / Местоположение на декана\n"
                f"- Факултет: {lc.get('faculty')}\n"
                f"- Декан: {lc.get('dean')}\n"
                f"- КАБИНЕТ / ЛОКАЦИЯ: Кабинет {lc.get('cabinet')}, {lc.get('location')}"
            )
        else:
            parts.append(
                f"ФОКУС: Контакти на декана\n"
                f"- Факултет: {lc.get('faculty')}\n"
                f"- Декан: {lc.get('dean')}\n"
                f"- ТЕЛЕФОН: {lc.get('phone')}\n"
                f"- Кабинет: {lc.get('cabinet')}, {lc.get('location')}\n"
                f"- Email: {lc.get('email')}"
            )

    elif "dean_info" in grounded_facts:
        d = grounded_facts["dean_info"]
        parts.append(
            f"ФОКУС: Ръководство / Декан\n"
            f"- Факултет: {d.get('faculty')}\n"
            f"- ДЕКАН: {d.get('dean')}\n"
            f"- Кабинет: {d.get('cabinet')}, {d.get('location')}\n"
            f"- Телефон: {d.get('phone')}\n"
            f"- Email: {d.get('email')}"
        )

    elif "faculty_disambiguation" in grounded_facts:
        fd = grounded_facts["faculty_disambiguation"]
        ex_lines = [f"  * {item['code']} ({item['name']}): декан {item['dean']}" for item in fd.get("examples", [])]
        parts.append(
            f"ФОКУС: Уточняване за декан\n"
            f"- Общ брой факултети в ТУ-София: {fd.get('total_faculties', 17)}\n"
            f"- Всеки факултет има собствен декан. Обясни любезно това и попитай за кой факултет става дума (напр. {', '.join([x['code'] for x in fd.get('examples', [])])})."
        )

    # 5. Curriculum Info
    if "curriculum_info" in grounded_facts:
        ci = grounded_facts["curriculum_info"]
        parts.append(
            f"ФОКУС: Учебен профил и дисциплини\n"
            f"- Специалност: {ci.get('specialty_name')}\n"
            f"- Факултет: {ci.get('primary_faculty')}\n"
            f"- Основни технологии и дисциплини: {ci.get('focus_areas')}\n"
            f"- Степен: {ci.get('degree')}"
        )

    # 6. Faculty Specialties List
    if "faculty_specialties" in grounded_facts:
        fspec = grounded_facts["faculty_specialties"]
        specs_str = ", ".join(fspec.get("specialties", []))
        parts.append(
            f"ФОКУС: Специалности във факултета\n"
            f"- Факултет: {fspec.get('faculty')}\n"
            f"- Специалности: {specs_str}"
        )

    # 7. Admissions Calendar
    if "admissions_calendar" in grounded_facts:
        cal = grounded_facts["admissions_calendar"]
        lines = [f"- {d['activity']}: {d['deadline']}" for d in cal.get("key_deadlines", [])]
        parts.append(f"ФОКУС: Календар за кандидатстване 2026/2027\n" + "\n".join(lines))

    # 8. Dormitories
    if "dormitories" in grounded_facts:
        dm = grounded_facts["dormitories"].get("contacts", {})
        parts.append(
            f"ФОКУС: Общежития и столове (ПССО)\n"
            f"- Локация: {dm.get('location', 'Студентски град, София')}\n"
            f"- Капацитет: {dm.get('capacity', 'над 6000 места')}"
        )

    # 9. Rectorate
    if "rectorate" in grounded_facts:
        rc = grounded_facts["rectorate"].get("contacts", {})
        parts.append(
            f"ФОКУС: Ректорат ТУ-София\n"
            f"- Ректор: {rc.get('rector')}\n"
            f"- Адрес: {rc.get('address')}\n"
            f"- Телефон: {rc.get('phone')}"
        )

    # 10. General Summaries
    if "specialty_summary" in grounded_facts:
        ss = grounded_facts["specialty_summary"]
        parts.append(
            f"ФОКУС: Общ преглед на специалност\n"
            f"- Име: {ss.get('name')}\n"
            f"- Факултет: {ss.get('primary_faculty')}\n"
            f"- Профил: {ss.get('focus')}\n"
            f"- Такса: {ss.get('semester_fee')}"
        )

    if "faculty_summary" in grounded_facts:
        fs = grounded_facts["faculty_summary"]
        parts.append(
            f"ФОКУС: Общ преглед на факултет\n"
            f"- Факултет: {fs.get('name')} ({fs.get('code')})\n"
            f"- Декан: {fs.get('dean')}\n"
            f"- Примерни специалности: {', '.join(fs.get('specialties_preview', []))}"
        )

    if "top_matches" in grounded_facts and not parts:
        matches = grounded_facts["top_matches"][:2]
        match_str = "\n".join([f"- {m.get('title')}: {m.get('snippet')}" for m in matches])
        parts.append(f"ДРУГИ СЪВПАДЕНИЯ:\n{match_str}")

    return "\n\n".join(parts) if parts else "Няма намерени специфични записи."


def synthesize_fallback_response(user_message: str, facts: dict) -> str:
    """
    Conversational fallback synthesizing Laya's selected facts directly and concisely,
    never dumping massive raw JSON text or endless bullet lists.
    """
    # 1. Specialty Fee
    if "specialty_fee" in facts:
        sf = facts["specialty_fee"]
        lang_note = f" {sf.get('language_module')}" if sf.get("language_module") else ""
        return (
            f"Семестриалната такса за специалност **{sf.get('specialty_name')}** по държавна поръчка "
            f"е **{sf.get('semester_fee')}** към {sf.get('primary_faculty')}.{lang_note}"
        )

    # 2. General Fees
    if "general_fees" in facts:
        gf = facts["general_fees"]
        return (
            f"Семестриалните такси по държавна поръчка за общите инженерни специалности в ТУ-София са между **{gf.get('standard_engineering_fee', '350 и 550 лв.')}**. "
            f"За специалност ИСИГД/SICH таксата е **{gf.get('sich_fee', '600 лв. (300 евро)')}**, "
            f"а кандидатстудентската такса за изпит или признаване на матура е **{gf.get('application_fee', '30 евро (60 лв.)')}**."
        )

    # 3. Specialty Faculty Affiliation
    if "specialty_faculty" in facts:
        sfac = facts["specialty_faculty"]
        lang_part = f" За обучението на английски език ({sfac.get('english_module')}) тя се координира съвместно с ФАИО." if sfac.get("english_module") else ""
        return f"Специалността **{sfac.get('specialty_name')}** се обучава и администрира към **{sfac.get('primary_faculty')}**.{lang_part}"

    # 4. Dean / Leadership Contact & Leadership Info
    if "leadership_contact" in facts:
        lc = facts["leadership_contact"]
        target = lc.get("target_type", "all")
        if target == "phone":
            return f"Телефонният номер на декана на {lc.get('faculty')} ({lc.get('dean')}) е **{lc.get('phone')}**."
        elif target == "email":
            return f"Имейлът на декана на {lc.get('faculty')} ({lc.get('dean')}) е **{lc.get('email')}**."
        elif target == "cabinet":
            return f"Деканът на {lc.get('faculty')} ({lc.get('dean')}) приема в **кабинет {lc.get('cabinet')}**, {lc.get('location')}."
        else:
            return f"Декан на {lc.get('faculty')} е **{lc.get('dean')}**. Телефон: **{lc.get('phone')}**, кабинет {lc.get('cabinet')} ({lc.get('location')})."

    if "dean_info" in facts:
        d = facts["dean_info"]
        contacts = []
        if d.get("cabinet") and d.get("cabinet") != "Н/А":
            contacts.append(f"каб. {d.get('cabinet')}")
        if d.get("location"):
            contacts.append(d.get("location"))
        if d.get("phone"):
            contacts.append(f"тел. {d.get('phone')}")
        if d.get("email"):
            contacts.append(f"email: {d.get('email')}")
        contact_str = f" ({', '.join(contacts)})" if contacts else ""
        return f"Декан на **{d.get('faculty')}** е **{d.get('dean')}**{contact_str}."

    if "faculty_disambiguation" in facts:
        fd = facts["faculty_disambiguation"]
        ex_codes = ", ".join([x["code"] for x in fd.get("examples", [])[:4]])
        return (
            f"В ТУ-София има {fd.get('total_faculties', 17)} факултета и филиала, всеки със свой декан. "
            f"За кой точно факултет търсите ръководство? (напр. {ex_codes})"
        )

    # 5. Curriculum
    if "curriculum_info" in facts:
        ci = facts["curriculum_info"]
        return f"В специалност **{ci.get('specialty_name')}** към {ci.get('primary_faculty')} студентите се обучават в областта на: {ci.get('focus_areas')} (ОКС {ci.get('degree')})."

    # 6. Faculty Specialties
    if "faculty_specialties" in facts:
        fspec = facts["faculty_specialties"]
        specs_list = fspec.get("specialties", [])
        return f"В **{fspec.get('faculty')}** се изучават следните бакалавърски специалности:\n" + "\n".join([f"• {s}" for s in specs_list])

    # 7. Calendar
    if "admissions_calendar" in facts:
        cal = facts["admissions_calendar"]
        lines = [f"• **{d['activity']}:** {d['deadline']}" for d in cal.get("key_deadlines", [])]
        return "Основни срокове за кандидатстудентската кампания:\n" + "\n".join(lines)

    # 8. Dormitories
    if "dormitories" in facts:
        dm = facts["dormitories"].get("contacts", {})
        return f"Поделение „Студентски столове и общежития“ (ПССО) разполага с {dm.get('capacity', 'над 6000 места')} в {dm.get('location', 'Студентски град, София')}."

    # 9. Rectorate
    if "rectorate" in facts:
        rc = facts["rectorate"].get("contacts", {})
        return f"Ректоратът на ТУ-София се намира на **{rc.get('address')}** с Ректор **{rc.get('rector')}** (тел. {rc.get('phone')})."

    # 10. General Specialty Summary
    if "specialty_summary" in facts:
        ss = facts["specialty_summary"]
        return (
            f"Специалността **{ss.get('name')}** се провежда към {ss.get('primary_faculty')}. "
            f"Тя предлага {ss.get('focus')}, а семестриалната такса по държавна поръчка е {ss.get('semester_fee')}."
        )

    # 11. General Faculty Summary
    if "faculty_summary" in facts:
        fs = facts["faculty_summary"]
        return (
            f"**{fs.get('name')} ({fs.get('code')})** се ръководи от декан **{fs.get('dean')}**. "
            f"Факултетът обучава студенти по специалности като: {', '.join(fs.get('specialties_preview', []))}."
        )

    # Default fallback
    if "top_matches" in facts:
        m = facts["top_matches"][0]
        return f"Според официалната база на ТУ-София ({m.get('title')}): {m.get('snippet')}"

    return (
        "Не открих конкретна информация за това запитване в базата данни на ТУ-София. "
        "За точна справка можете да се обърнете към Учебен отдел (тел. 02 965 21 11) или priem.tu-sofia.bg."
    )


def call_gemma_chat(user_message: str, grounded_facts: dict) -> str:
    """
    Step 2: ТУдор (gemma4:e2b) receives Laya's selected facts and synthesizes
    a conversational, intelligent answer in 1-3 direct sentences without long data dumps.
    """
    facts_summary = prepare_facts_for_gemma(grounded_facts, user_message)

    system_prompt = f"""Ти си ТУдор - експертен, интелигентен и стегнат AI съветник на Технически университет - София.
Laya вече подбра и верифицира точните факти от базата за конкретния въпрос.

{facts_summary}

ТВОИТЕ ПРАВИЛА:
1. СИНТЕЗИРАЙ кратък, жив и директен отговор (1 до 2 изречения) на български език, отговарящ ТОЧНО на това, което потребителят пита.
2. НЕ заливай потребителя с 2000 думи или механични списъци с точки! Потребителят търси бърз, ясен и синтезиран отговор.
3. Отговори директно по същество без встъпителни клишета ("Здравейте, аз съм ТУдор...").
4. Ако потребителят пита за "номер", "телефон", "имейл" или "кабинет" — започни ДИРЕКТНО с искания телефонен номер или контакт! НИКОГА не отговаряй само с името на декана, ако въпросът е за номер или телефон.
5. Ако питат за такса — посочи конкретната такса и най-същественото уточнение (държавна поръчка, модул). Не изброявай излишни предмети или квалификации.
6. Ако питат "кой е декан" или за факултет — посочи директно факултета или декана и контактите му.
7. Използвай ЕДИНСТВЕНО фактите по-горе от Laya. Не си измисляй нищо."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        t0 = time.time()
        resp = httpx.post(
            OLLAMA_CHAT_URL,
            json={
                "model": GEMMA_MODEL,
                "messages": messages,
                "think": False,
                "stream": False,
                "options": {
                    "num_predict": 120,
                    "temperature": 0.25
                }
            },
            timeout=60.0
        )
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("message", {}).get("content", "").strip()
            if reply:
                print(f"[INFO] ТУдор (Gemma 4:e2b) synthesized reply in {time.time()-t0:.2f}s")
                return reply
        else:
            print(f"[WARN] Ollama status: {resp.status_code}")
    except Exception as e:
        print(f"[INFO] ТУдор fallback triggered ({e}). Serving verified Laya response.")

    return synthesize_fallback_response(user_message, grounded_facts)




class LayaRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            traceback.print_exc()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/api/chat":
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                    post_body = self.rfile.read(content_length).decode("utf-8")
                    data = json.loads(post_body) if post_body else {}
                    user_msg = data.get("message", "").strip()
                except Exception as e:
                    self.send_json({"error": f"Invalid request body: {str(e)}"}, status=400)
                    return

                if not user_msg:
                    self.send_json({"error": "Empty message"}, status=400)
                    return

                # Step 1: Laya finds the facts
                laya_facts, laya_reasoning = call_laya_retrieval(user_msg)

                # Step 2: ТУдор talks to user with Laya's facts
                tudor_reply = call_gemma_chat(user_msg, laya_facts)

                response_data = {
                    "status": "success",
                    "model_speaker": f"{BOT_NAME} ({GEMMA_MODEL})",
                    "model_retriever": "Laya (TU Sofia AI Decoder)",
                    "user_message": user_msg,
                    "gemma_response": tudor_reply,
                    "laya_reasoning": laya_reasoning,
                    "laya_grounding": laya_facts
                }

                self.send_json(response_data)
                return

            self.send_json({"error": "Endpoint not found"}, status=404)
        except Exception as ex:
            traceback.print_exc()
            self.send_json({"error": f"Internal Server Error: {str(ex)}"}, status=500)

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query_params = urllib.parse.parse_qs(parsed.query)

            # GET /api/chat support for testing
            if path == "/api/chat":
                user_msg = query_params.get("q", [""])[0]
                if not user_msg:
                    user_msg = "Кой е декан на ФКСТ?"

                laya_facts, laya_reasoning = call_laya_retrieval(user_msg)
                tudor_reply = call_gemma_chat(user_msg, laya_facts)

                response_data = {
                    "status": "success",
                    "model_speaker": f"{BOT_NAME} ({GEMMA_MODEL})",
                    "model_retriever": "Laya (TU Sofia AI Decoder)",
                    "user_message": user_msg,
                    "gemma_response": tudor_reply,
                    "laya_reasoning": laya_reasoning,
                    "laya_grounding": laya_facts
                }

                self.send_json(response_data)
                return

            # Standard API Routes
            if path.startswith("/api/"):
                response_data = {}

                if path == "/api/search":
                    q = query_params.get("q", [""])[0]
                    limit = int(query_params.get("limit", [5])[0])
                    results = search_tu_sofia(q, limit=limit)
                    response_data = {
                        "query": q,
                        "results_count": len(results),
                        "results": results
                    }

                elif path == "/api/faculty":
                    code = query_params.get("code", [""])[0]
                    response_data = get_faculty_info(code)

                elif path == "/api/admissions":
                    topic = query_params.get("topic", [None])[0]
                    response_data = get_admissions_info(topic=topic)

                elif path == "/api/curriculum":
                    faculty = query_params.get("faculty", [""])[0]
                    degree = query_params.get("degree", ["bachelor"])[0]
                    response_data = get_curriculum(faculty, degree=degree)

                elif path == "/api/contacts":
                    q = query_params.get("q", ["ректор"])[0]
                    response_data = get_contact_info(q)

                elif path == "/api/kb":
                    response_data = _load_kb()

                elif path == "/api/map":
                    response_data = _load_map()

                elif path == "/api/schemas":
                    response_data = {
                        "version": "1.0",
                        "tools_count": len(LAYA_TOOLS_SCHEMAS),
                        "schemas": LAYA_TOOLS_SCHEMAS
                    }

                elif path == "/api/m2m":
                    tool = query_params.get("tool", ["search_tu_sofia"])[0]
                    q = query_params.get("q", ["ФКСТ"])[0]
                    dest = query_params.get("target", ["Downstream-AI-Agent"])[0]

                    if tool == "get_faculty_info":
                        raw_res = get_faculty_info(q)
                    elif tool == "get_admissions_info":
                        raw_res = get_admissions_info(q)
                    elif tool == "get_curriculum":
                        raw_res = get_curriculum(q)
                    else:
                        raw_res = search_tu_sofia(q)

                    response_data = format_tool_payload_for_model(tool, raw_res, destination_model=dest)

                else:
                    response_data = {"error": f"Unknown endpoint {path}"}

                self.send_json(response_data)
                return

            # Serve static assets
            return super().do_GET()
        except Exception as ex:
            traceback.print_exc()
            self.send_json({"error": f"Internal Server Error: {str(ex)}"}, status=500)


def run_server(port=8080):
    ThreadingHTTPServer.allow_reuse_address = True
    server_address = ('', port)
    httpd = ThreadingHTTPServer(server_address, LayaRequestHandler)
    print(f"[*] Laya TU Sofia Explorer Server (Multi-threaded) running on http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    port = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
