"""
Lightweight REST API & Web Server for Laya TU Sofia Explorer.
Coordinates Laya (the AI semantic decoder/retriever) with ТУдор (gemma4:e2b, the conversational speaker)
to provide a grounded, hallucination-free AI assistant for TU Sofia.
"""

import os
import sys
import json
import time
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
    _load_kb,
    _load_map
)
from crawler.bulgarian_nlp import resolve_acronym_or_alias, normalize_bulgarian_text, transliterate_to_cyrillic

APP_DIR = os.path.dirname(__file__)
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
GEMMA_MODEL = "gemma4:e2b"
BOT_NAME = "ТУдор"


def call_laya_retrieval(query: str):
    """
    Step 1: Laya decodes user intent, expands Bulgarian acronyms,
    supports shlokavica/Latin transliteration, and extracts grounded facts from the local knowledge base.
    """
    normalized_q = normalize_bulgarian_text(query).lower()
    cyr_q = transliterate_to_cyrillic(normalized_q).lower()
    facts = {}
    reasoning = []

    # 1. Check for specific specialties (e.g. ИСИГД, АЕ, КСТ, АИО)
    if any(k in normalized_q or k in cyr_q for k in ["исигд", "интелигентни системи в индустрията", "isigd"]):
        facts["specialty"] = {
            "name": "Интелигентни системи в индустрията, града и дома (ИСИГД)",
            "english_module": "Специализирано обучение на английски език (АЕ)",
            "faculties": "Факултет по автоматика (ФА) и Факултет за английско инженерно обучение (ФАИО)",
            "degree": "Бакалавър / Магистър",
            "description": "Модерна интердисциплинарна инженерна специалност, обединяваща IoT, изкуствен интелект, интелигентни сгради, градове и автоматизация."
        }
        reasoning.append("Laya разпозна специалност 'ИСИГД (АЕ)' -> Интелигентни системи в индустрията, града и дома (към ФА / ФАИО на английски език).")

    # 2. Check for faculty acronym or name (handles Cyrillic, Latin, and shlokavica)
    acronym_info = resolve_acronym_or_alias(query)
    if acronym_info:
        code = acronym_info["code"]
        fac_info = get_faculty_info(code)
        if fac_info.get("status") == "success":
            facts["faculty"] = fac_info
            matched_term = acronym_info.get("matched", code)
            reasoning.append(f"Laya разпозна факултет '{code}' (чрез '{matched_term}') -> {fac_info.get('name_bg')}. Извлечени: Декан {fac_info['leadership']['dean']}, катедри, контакти.")

    # 2b. Check for generic dean/leadership query WITHOUT a specific faculty
    is_leadership_query = any(k in normalized_q or k in cyr_q for k in ["декан", "шеф", "dekan", "shef", "ръководител", "head"])
    if is_leadership_query and "faculty" not in facts:
        kb = _load_kb()
        examples = [{"code": f.get("acronym"), "name": f.get("name_bg"), "dean": f.get("dean")} for f in kb.get("faculties", [])[:5]]
        facts["faculty_disambiguation"] = {
            "prompt": "В ТУ-София има 17 основни факултета и филиали, всеки от които се ръководи от собствен декан.",
            "examples": examples,
            "total_faculties": len(kb.get("faculties", []))
        }
        reasoning.append("Laya засече запитване за декан/ръководство без конкретизиран факултет. Предложено уточняване на факултета.")

    # 3. Check for admissions, fees, tuition per semester, state quota
    fee_triggers = [
        "такса", "такси", "цена", "цени", "пари", "струва", "семестър", 
        "семестриалн", "държавна поръчка", "платено", "плаща", "fee", "cost", "taksi", "taksa"
    ]
    if any(k in normalized_q or k in cyr_q for k in fee_triggers):
        fees = get_admissions_info(topic="fees")
        facts["admissions_fees"] = fees
        facts["tuition_policy"] = {
            "application_fee": "30 евро (60 лв.) за явяване на кандидатстудентски изпит или признаване на държавен зрелостен изпит (матура)",
            "state_subsidy": "Обучението по 'държавна поръчка' е субсидирано от държавния бюджет съгласно Закона за висшето образование (ЗВО).",
            "semester_tuition": "Семестриалните такси за редовно обучение по държавна поръчка се определят ежегодно с Постановление на Министерския съвет (ПМС) и заповед на Ректора. За инженерните специалности в ТУ-София таксата е субсидирана и варира между ~350 и 550 лв. на семестър.",
            "foreign_language_programs": "За специалности с преподаване на английски език (АЕ/ФАИО) се прилага съответната утвърдена държавна семестриална такса за направлението.",
            "preliminary_exam_rule": "Кандидат-студентите, ползващи резултати от предварителни изпити, подават документи за класиране БЕЗ допълнителна такса.",
            "payment_deadline": "Таксите за семестъра се заплащат в началото на всеки семестър чрез банков превод или през университетската система ЕТУС към Учебен отдел."
        }
        reasoning.append("Laya извлече официални такси: кандидатстване 30 евро; семестриална такса по държавна поръчка (субсидирана по ЗВО/ПМС ~350-550 лв/семестър).")

    # 4. Check for admissions calendar
    if any(k in normalized_q or k in cyr_q for k in ["график", "срок", "срокове", "кога", "дата", "дати", "прием", "изпит", "изпити", "calendar", "priem"]):
        cal = get_admissions_info(topic="calendar")
        facts["admissions_calendar_2026"] = cal
        reasoning.append(f"Laya извлече {len(cal.get('deadlines', []))} календарни дати за кандидатстудентска кампания 2026/2027.")

    # 5. Check for campus life, dormitories
    if any(k in normalized_q or k in cyr_q for k in ["общежити", "стол", "пссо", "стаи", "настаняване", "dorm", "obshtejiti"]):
        dorm = get_contact_info("общежития")
        facts["dormitories"] = dorm
        reasoning.append("Laya извлече контакти и локация на ПССО (Студентски град, над 6000 места).")

    # 6. Check for rectorate
    if any(k in normalized_q or k in cyr_q for k in ["ректор", "централа", "деловодство", "учебен отдел", "rektor"]):
        rectorate = get_contact_info("ректор")
        facts["rectorate"] = rectorate
        reasoning.append("Laya извлече контакти на Ректората (бул. Климент Охридски 8, Ректор проф. Георги Венков).")

    # 7. Broader semantic search: ONLY when no primary entities were found
    if not any(k in facts for k in ["specialty", "faculty", "faculty_disambiguation", "tuition_policy", "admissions_fees", "dormitories", "rectorate", "admissions_calendar_2026"]):
        search_results = search_tu_sofia(query, limit=3)
        if search_results:
            facts["top_matches"] = search_results

    if not reasoning:
        if "top_matches" in facts:
            reasoning.append(f"Laya извърши семантично търсене в базата от знания и откри {len(facts['top_matches'])} релевантни съвпадения.")
        else:
            reasoning.append("Laya прегледа запитването в семантичния граф на ТУ-София.")

    return facts, " | ".join(reasoning)



def prepare_facts_for_gemma(grounded_facts: dict) -> str:
    """
    Condenses the raw facts dictionary into a concise, high-density factual text
    so ТУдор (gemma4:e2b) evaluates the prompt in ~1-2 seconds.
    """
    parts = []

    if "specialty" in grounded_facts:
        sp = grounded_facts["specialty"]
        parts.append(
            f"СПЕЦИАЛНОСТ: {sp.get('name')}\n"
            f"- Модул/Език: {sp.get('english_module')}\n"
            f"- Факултети: {sp.get('faculties')}\n"
            f"- ОКС: {sp.get('degree')}\n"
            f"- Профил: {sp.get('description')}"
        )

    if "tuition_policy" in grounded_facts:
        tp = grounded_facts["tuition_policy"]
        parts.append(
            f"ТАКСИ И ДЪРЖАВНА ПОРЪЧКА:\n"
            f"- Семестриална такса (държавна поръчка): {tp.get('semester_tuition')}\n"
            f"- Субсидия: {tp.get('state_subsidy')}\n"
            f"- Кандидатстване (2026 г.): {tp.get('application_fee')}\n"
            f"- Програми на английски език (АЕ): {tp.get('foreign_language_programs')}\n"
            f"- Плащане: {tp.get('payment_deadline')}"
        )

    if "faculty" in grounded_facts:
        f = grounded_facts["faculty"]
        lead = f.get("leadership", {})
        parts.append(
            f"ФАКУЛТЕТ: {f.get('name_bg')} ({f.get('code', '')})\n"
            f"- Декан: {lead.get('dean', 'Н/А')}\n"
            f"- Кабинет/Сграда: {lead.get('location', '')}, каб. {lead.get('cabinet', '')}\n"
            f"- Телефон: {lead.get('phone', '')}\n"
            f"- Email: {lead.get('email', '')}\n"
            f"- Катедри: {', '.join(f.get('departments', []))}"
        )

    if "faculty_disambiguation" in grounded_facts:
        fd = grounded_facts["faculty_disambiguation"]
        ex_str = "\n".join([f"- {item['code']} ({item['name']}): декан {item['dean']}" for item in fd.get("examples", [])])
        parts.append(
            f"УТОЧНЯВАНЕ ЗА ФАКУЛТЕТИ И ДЕКАНИ:\n"
            f"В ТУ-София има {fd.get('total_faculties', 17)} основни факултета и филиали, като всеки се ръководи от свой декан.\n"
            f"Потребителят пита за декан или шеф без да уточни факултета. Обясни любезно това и го попитай за кой факултет се интересува, като дадеш примери:\n"
            f"{ex_str}"
        )

    if "admissions_fees" in grounded_facts and "tuition_policy" not in grounded_facts:
        fees = grounded_facts["admissions_fees"].get("fees_structure", {})
        parts.append(
            f"ТАКСИ ЗА КАНДИДАТСТВАНЕ 2026/2027:\n"
            f"- Изпитна такса / матура: {fees.get('exam_fee', '30 евро за изпит / признаване на матура')}\n"
            f"- Предварителни изпити: {fees.get('preliminary_exam_rule', '')}"
        )

    if "admissions_calendar_2026" in grounded_facts:
        deadlines = grounded_facts["admissions_calendar_2026"].get("deadlines", [])[:4]
        dead_lines_str = "\n".join([f"- {d['activity']}: {d['deadline']}" for d in deadlines])
        parts.append(f"КАЛЕНДАРЕН ГРАФИК ПРИЕМ 2026:\n{dead_lines_str}")

    if "dormitories" in grounded_facts:
        d = grounded_facts["dormitories"].get("contacts", {})
        parts.append(
            f"ОБЩЕЖИТИЯ (ПССО):\n"
            f"- Локация: {d.get('location', 'Студентски град, София')}\n"
            f"- Капацитет: {d.get('capacity', 'над 6000 легла')}\n"
            f"- Блокове: {d.get('blocks', '1, 2, 3, 4, 8, 9, 10 и др.')}"
        )

    if "rectorate" in grounded_facts:
        r = grounded_facts["rectorate"].get("contacts", {})
        parts.append(
            f"РЕКТОРАТ ТУ-СОФИЯ:\n"
            f"- Ректор: {r.get('rector', 'проф. д-р инж. Георги Венков')}\n"
            f"- Адрес: {r.get('address', 'бул. Климент Охридски 8')}\n"
            f"- Телефон: {r.get('phone', '02 965 21 11')}"
        )

    if "top_matches" in grounded_facts and not ("specialty" in grounded_facts or "faculty" in grounded_facts):
        matches = grounded_facts["top_matches"][:2]
        match_str = "\n".join([f"- {m.get('title')}: {m.get('snippet')}" for m in matches])
        parts.append(f"ДРУГИ СЪВПАДЕНИЯ:\n{match_str}")

    return "\n\n".join(parts) if parts else "Няма намерени специфични записи."


def call_gemma_chat(user_message: str, grounded_facts: dict) -> str:
    """
    Step 2: ТУдор (gemma4:e2b) receives Laya's grounded facts and formulates
    a conversational, intelligent answer in Bulgarian without preamble.
    """
    facts_summary = prepare_facts_for_gemma(grounded_facts)

    system_prompt = f"""Ти си ТУдор - любезният, компетентен AI консултант на Технически университет - София.
Твоят модел-партньор Laya извлече следните официални проверени факти от базата на университета:

{facts_summary}

ТВОЯТА ЗАДАЧА:
1. Формулирай ясен, естествен и точен отговор с твои собствени думи на български език, базиран на фактите от Laya.
2. Не копирай механично заглавията и суровите редове от Laya - обясни информацията интелигентно и директно по същество на въпроса.
3. НЕ повтаряй 'Здравейте, аз съм ТУдор...' при всяко съобщение. Започни директно с отговора.
4. Говори ЕДИНСТВЕНО от фактите по-горе! Не си измисляй несъществуващи суми, факултети или правила."""

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
                    "num_predict": 180,
                    "temperature": 0.25
                }
            },
            timeout=35.0
        )
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("message", {}).get("content", "").strip()
            if reply:
                print(f"[INFO] ТУдор (Gemma 4:e2b) formulated reply in {time.time()-t0:.2f}s")
                return reply
        else:
            print(f"[WARN] Ollama status: {resp.status_code}")
    except Exception as e:
        print(f"[INFO] ТУдор fallback triggered ({e}). Serving verified Laya response.")

    return synthesize_fallback_response(user_message, grounded_facts)



def synthesize_fallback_response(user_message: str, facts: dict) -> str:
    """Conversational speaker response synthesizing Laya's exact facts without repetitive introductions."""
    lines = []

    # 1. Specialty block
    if "specialty" in facts:
        sp = facts["specialty"]
        lines.append(f"🎓 **Специалност: {sp.get('name')}**")
        lines.append(f"- **Обучение/Език:** {sp.get('english_module')}")
        lines.append(f"- **Факултет:** {sp.get('faculties')}")
        lines.append(f"- **ОКС:** {sp.get('degree')}")
        lines.append(f"- **Профил:** {sp.get('description')}\n")

    # 2. Tuition / State quota block
    if "tuition_policy" in facts:
        tp = facts["tuition_policy"]
        lines.append("💰 **Семестриални такси и държавна поръчка:**")
        lines.append(f"- **Такса на семестър (държавна поръчка):** {tp.get('semester_tuition')}")
        lines.append(f"- **Субсидия:** {tp.get('state_subsidy')}")
        lines.append(f"- **За програми на английски език (АЕ):** {tp.get('foreign_language_programs')}")
        lines.append(f"- **Кандидатстудентска такса 2026:** {tp.get('application_fee')}")
        lines.append(f"- **Предварителни изпити:** {tp.get('preliminary_exam_rule', '')}")
        lines.append(f"- **Срок и начин на плащане:** {tp.get('payment_deadline')}\n")
    elif "admissions_fees" in facts:
        fees = facts["admissions_fees"].get("fees_structure", {})
        lines.append("💰 **Такси за кандидатстване и изпити (2026 г.):**")
        lines.append(f"- {fees.get('exam_fee', '30 евро за изпит / признаване на матура')}")
        lines.append(f"- {fees.get('preliminary_exam_rule', '')}\n")

    # 3. Faculty block
    if "faculty" in facts:
        fac = facts["faculty"]
        lead = fac.get("leadership", {})
        lines.append(f"🏛 **{fac.get('name_bg')} ({fac.get('code', '')})**")
        lines.append(f"- **Декан:** {lead.get('dean', 'Н/А')}")
        lines.append(f"- **Локация:** {lead.get('location', '')}, каб. {lead.get('cabinet', '')}")
        lines.append(f"- **Телефон:** {lead.get('phone', '')}")
        lines.append(f"- **Email:** {lead.get('email', '')}")
        if fac.get("departments"):
            lines.append(f"- **Катедри:** {', '.join(fac['departments'])}")
        lines.append("")

    # 3b. Faculty disambiguation block
    if "faculty_disambiguation" in facts:
        fd = facts["faculty_disambiguation"]
        lines.append("🏛 **Ръководство на факултети в ТУ-София:**")
        lines.append(f"В ТУ-София функционират {fd.get('total_faculties', 17)} факултета и филиали, всеки от които се ръководи от собствен декан.")
        lines.append("Моля, посочете за кой факултет търсите информация (например):")
        for f in fd.get("examples", []):
            lines.append(f"- **{f['code']}** ({f['name']}): декан {f['dean']}")
        lines.append("\n_Посочете желания факултет (напр. 'декан на ФКСТ', 'декан на ФА', 'шеф на стопански'), за да ви покажа контактите и графика му!_\n")

    # 4. Admissions calendar block
    if "admissions_calendar_2026" in facts:
        deadlines = facts["admissions_calendar_2026"].get("deadlines", [])[:4]
        lines.append("📅 **Срокове от календарния график 2026:**")
        for d in deadlines:
            lines.append(f"- **{d['activity']}:** {d['deadline']}")
        lines.append("")

    # 5. Dormitories block
    if "dormitories" in facts:
        dorm = facts["dormitories"].get("contacts", {})
        lines.append(f"🏢 **Студентски столове и общежития (ПССО):** {dorm.get('location', '')} (Капацитет: {dorm.get('capacity', '')})\n")

    # 6. Rectorate block
    if "rectorate" in facts:
        r = facts["rectorate"].get("contacts", {})
        lines.append(f"🏛 **Ректорат ТУ-София:** {r.get('address', '')}, тел: {r.get('phone', '')}\n")

    # 7. Fallback matches from semantic search if specific blocks were not triggered
    if "top_matches" in facts and not any(k in facts for k in ["specialty", "tuition_policy", "faculty", "dormitories"]):
        lines.append("Намерена информация от семантичната база на ТУ-София:")
        for m in facts["top_matches"][:3]:
            lines.append(f"- **{m.get('title')}:** {m.get('snippet')}")
        lines.append("")

    if not lines:
        lines.append("Не открих конкретна информация за това запитване в базата данни. За точна справка можете да се обърнете към Учебен отдел на ТУ-София (тел. 02 965 21 11) или да проверите в priem.tu-sofia.bg.")
    else:
        lines.append("_Ако имате допълнителни въпроси за специалности или документи, насреща съм!_")

    return "\n".join(lines).strip()


class LayaRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
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

    def do_GET(self):
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
