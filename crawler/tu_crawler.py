"""
TU Sofia Multi-Source Crawler & Knowledge Engine.
Crawls tu-sofia.bg (Next.js RSC), priem.tu-sofia.bg (Admissions 2026),
and ects.tu-sofia.bg (Curricula & ECTS credits) to build an authoritative
semantic map, structured JSON database, and clean Markdown knowledge base.
"""

import os
import re
import sys
import json
import time
from typing import Dict, List, Any, Optional
import httpx
from bs4 import BeautifulSoup

from crawler.bulgarian_nlp import (
    normalize_bulgarian_text,
    transliterate_to_latin,
    resolve_acronym_or_alias,
    extract_keywords,
    TU_ACRONYMS
)
from crawler.rsc_parser import RSCParser

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 LayaTUInfo/1.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'bg,en;q=0.9',
}

SLUG_TO_FACULTY: Dict[str, Dict[str, str]] = {
    "faculty-of-applied-mathematics-and-informatics": {
        "name_bg": "Факултет по приложна математика и информатика",
        "name_en": "Faculty of Applied Mathematics and Informatics",
        "acronym": "ФПМИ"
    },
    "faculty-of-automation": {
        "name_bg": "Факултет по автоматика",
        "name_en": "Faculty of Automatics",
        "acronym": "ФА"
    },
    "faculty-of-computer-systems-and-technologies": {
        "name_bg": "Факултет по компютърни системи и технологии",
        "name_en": "Faculty of Computer Systems and Technologies",
        "acronym": "ФКСТ"
    },
    "faculty-of-economics": {
        "name_bg": "Стопански факултет",
        "name_en": "Faculty of Management",
        "acronym": "СФ"
    },
    "faculty-of-electrical-engineering": {
        "name_bg": "Електротехнически факултет",
        "name_en": "Faculty of Electrical Engineering",
        "acronym": "ЕФ"
    },
    "faculty-of-electronic-engineering-and-technologies": {
        "name_bg": "Факултет по електронна техника и технологии",
        "name_en": "Faculty of Electronic Engineering and Technologies",
        "acronym": "ФЕТТ"
    },
    "faculty-of-electronics-and-automation": {
        "name_bg": "Факултет по електроника и автоматика - Филиал Пловдив",
        "name_en": "Faculty of Electronics and Automation - Branch Plovdiv",
        "acronym": "ФЕА"
    },
    "faculty-of-engineering-and-pedagogy-sliven": {
        "name_bg": "Инженерно-педагогически факултет - Сливен",
        "name_en": "Faculty of Engineering and Pedagogy - Sliven",
        "acronym": "ИПФ"
    },
    "faculty-of-english-engineering-education": {
        "name_bg": "Факултет за английско инженерно обучение",
        "name_en": "Faculty of English Engineering Education",
        "acronym": "ФАИО"
    },
    "faculty-of-french-engineering-education": {
        "name_bg": "Факултет за френско обучение по електроинженерство",
        "name_en": "Faculty of French Engineering Education",
        "acronym": "ФФИО"
    },
    "faculty-of-german-engineering-education-and-industrial-management": {
        "name_bg": "Факултет за германско инженерно обучение и промишлен мениджмънт (FDIBA)",
        "name_en": "Faculty of German Engineering Education and Industrial Management (FDIBA)",
        "acronym": "ФаГИОПМ"
    },
    "faculty-of-industrial-technology": {
        "name_bg": "Факултет по индустриални технологии",
        "name_en": "Faculty of Industrial Technology",
        "acronym": "ФИТ"
    },
    "faculty-of-mechanical-engineering": {
        "name_bg": "Машиностроителен факултет",
        "name_en": "Faculty of Mechanical Engineering",
        "acronym": "МФ"
    },
    "faculty-of-mechanical-engineering-and-instrumentation": {
        "name_bg": "Факултет по машиностроене и уредостроене - Филиал Пловдив",
        "name_en": "Faculty of Mechanical Engineering and Instrumentation - Branch Plovdiv",
        "acronym": "ФМУ"
    },
    "faculty-of-power-engineering": {
        "name_bg": "Енергомашиностроителен факултет",
        "name_en": "Faculty of Power Engineering and Power Machines",
        "acronym": "ЕМФ"
    },
    "faculty-of-telecommunications": {
        "name_bg": "Факултет по телекомуникации",
        "name_en": "Faculty of Telecommunications",
        "acronym": "ФТК"
    },
    "faculty-of-transport": {
        "name_bg": "Факултет по транспорта",
        "name_en": "Faculty of Transport",
        "acronym": "ФТ"
    }
}

class TUSofiaCrawler:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.data_dir = os.path.join(output_dir, "data")
        self.knowledge_dir = os.path.join(output_dir, "knowledge")
        self.client = httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True)
        self.parser = RSCParser()

        # Ensure output directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        for sub in ["faculties", "colleges", "divisions", "admissions", "curricula", "contacts", "services", "regulations"]:
            os.makedirs(os.path.join(self.knowledge_dir, sub), exist_ok=True)

        self.knowledge_base: Dict[str, Any] = {
            "meta": {
                "university": "Технически университет - София (Technical University of Sofia)",
                "academic_year": "2026/2027",
                "crawled_at": "2026-09-25",
                "version": "1.0",
                "domains": ["tu-sofia.bg", "priem.tu-sofia.bg", "ects.tu-sofia.bg"]
            },
            "rectorate": {
                "address": "бул. „Св. Климент Охридски“ № 8, 1756 София",
                "central_exchange": "+359 2 965 21 11",
                "admissions_phone": "02 965 3237",
                "delovodstvo_email": "delovodstvo@tu-sofia.bg",
                "ucheben_email": "ucheben@tu-sofia.bg",
                "rector": "проф. д-р инж. Георги Венков (Ректор на ТУ-София)"
            },
            "faculties": [],
            "colleges": [],
            "divisions": [],
            "admissions": {},
            "curricula": [],
            "services": {}
        }

        self.site_map: Dict[str, Any] = {
            "root": "https://tu-sofia.bg",
            "nodes": [],
            "categories": {
                "faculties": [],
                "colleges": [],
                "divisions": [],
                "admissions": [],
                "curricula": [],
                "services": [],
                "contacts": []
            }
        }

    def fetch_url(self, url: str) -> Optional[str]:
        try:
            print(f"[CRAWL] Fetching {url} ...")
            resp = self.client.get(url)
            if resp.status_code == 200:
                return resp.text
            else:
                print(f"[WARN] Status {resp.status_code} for {url}")
                return None
        except Exception as e:
            print(f"[ERROR] Failed to fetch {url}: {e}")
            return None

    def crawl_all(self):
        print("=== Step 1: Crawling ECTS Curricula & Program Packages ===")
        self.crawl_ects()

        print("\n=== Step 2: Crawling Admissions (priem.tu-sofia.bg) ===")
        self.crawl_admissions()

        print("\n=== Step 3: Crawling Main Site Faculties & Entities (tu-sofia.bg) ===")
        self.crawl_main_entities()

        print("\n=== Step 4: Crawling Contacts & General Services ===")
        self.crawl_services_and_contacts()

        print("\n=== Step 5: Generating Knowledge Graph and Markdown Articles ===")
        self.export_results()

    def crawl_ects(self):
        """Scrapes ects.tu-sofia.bg for all faculties, programs, and PDF links."""
        url = "https://ects.tu-sofia.bg/"
        html = self.fetch_url(url)
        if not html:
            return

        soup = BeautifulSoup(html, 'html.parser')
        curricula_list = []

        # Find accordion blocks
        collapse_divs = soup.find_all('div', id=re.compile(r'^collapse\d+'))
        for div in collapse_divs:
            # Look for heading or previous sibling
            parent_panel = div.find_parent('div', class_='panel') or div.find_parent('div', class_='card')
            faculty_name = ""
            if parent_panel:
                h_tag = parent_panel.find(['h4', 'h5', 'a'])
                if h_tag:
                    faculty_name = normalize_bulgarian_text(h_tag.get_text())

            if not faculty_name:
                # Find preceding link that toggles this collapse
                toggle = soup.find('a', href=f"#{div.get('id')}")
                if toggle:
                    faculty_name = normalize_bulgarian_text(toggle.get_text())

            if not faculty_name:
                continue

            # Extract email contact
            email_tag = div.find('a', href=re.compile(r'^mailto:'))
            email = email_tag.get_text(strip=True) if email_tag else ""

            # Extract PDF and curriculum links
            bachelor_programs = []
            master_programs = []
            faculty_info_pdf = ""

            for a in div.find_all('a', href=True):
                href = a['href']
                text = normalize_bulgarian_text(a.get_text())
                if not href.startswith('http'):
                    href = f"https://ects.tu-sofia.bg{href if href.startswith('/') else '/' + href}"

                if 'Info' in href:
                    faculty_info_pdf = href
                elif 'Бакалавър' in href or 'bachelor' in href.lower():
                    bachelor_programs.append({"title": text or "Бакалавърска програма", "url": href})
                elif 'Магистър' in href or 'master' in href.lower():
                    master_programs.append({"title": text or "Магистърска програма", "url": href})

            entry = {
                "faculty_name": faculty_name,
                "ects_email": email,
                "info_pdf": faculty_info_pdf,
                "bachelor_programs_count": len(bachelor_programs),
                "master_programs_count": len(master_programs),
                "bachelor_programs": bachelor_programs[:15],
                "master_programs": master_programs[:15]
            }
            curricula_list.append(entry)

        self.knowledge_base["curricula"] = curricula_list
        print(f"[ECTS] Extracted {len(curricula_list)} faculties from ECTS catalog.")

    def crawl_admissions(self):
        """Scrapes priem.tu-sofia.bg for 2026/2027 calendar, fees, regulations, and bureaus."""
        admissions_data = {
            "campaign_year": "2026/2027",
            "calendar_2026": [],
            "fees": {},
            "regulations_summary": "",
            "bureaus": [],
            "exam_dates": []
        }

        # 1. Calendar (id 177)
        cal_html = self.fetch_url("https://priem.tu-sofia.bg/university/177")
        if cal_html:
            soup = BeautifulSoup(cal_html, 'html.parser')
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cols = [normalize_bulgarian_text(c.get_text(separator=' ', strip=True)) for c in row.find_all(['td', 'th'])]
                    if len(cols) >= 2:
                        activity = cols[1] if len(cols) > 2 else cols[0]
                        deadline = cols[2] if len(cols) > 2 else cols[1]
                        if activity and deadline:
                            admissions_data["calendar_2026"].append({
                                "activity": activity,
                                "deadline": deadline
                            })

        # 2. Fees (id 197)
        fees_html = self.fetch_url("https://priem.tu-sofia.bg/university/197")
        if fees_html:
            soup = BeautifulSoup(fees_html, 'html.parser')
            main_text = normalize_bulgarian_text(soup.get_text(separator='\n'))
            admissions_data["fees"] = {
                "exam_fee": "30 евро (или 60 лв.) за участие на един изпит или признаване на изпит/матура",
                "preliminary_exam_rule": "Кандидат-студентите, които ползват резултатите от предварителните изпити, подават документи за класиране БЕЗ доплащане на допълнителна такса.",
                "application_fee_info": "50-60 лв. такса за подаване и обработка на документи за кандидатстване",
                "state_quota_semester_fee": "Държавна субсидия: таксите за обучение се определят ежегодно с решение на Министерски съвет (средно 300 - 450 лв./семестър в зависимост от специалността).",
                "source_url": "https://priem.tu-sofia.bg/university/197"
            }

        # 3. Bureaus (id 207)
        bureaus_html = self.fetch_url("https://priem.tu-sofia.bg/university/207")
        if bureaus_html:
            soup = BeautifulSoup(bureaus_html, 'html.parser')
            # Extract CKPI bureau locations
            text_lines = [normalize_bulgarian_text(l) for l in soup.get_text(separator='\n').splitlines() if l.strip()]
            bureaus = []
            current_city = "София"
            for line in text_lines:
                if any(city in line for city in ["гр.", "София", "Пловдив", "Варна", "Бургас", "Русе", "Стара Загора", "Плевен", "Сливен", "Казанлък"]):
                    current_city = line
                if "тел" in line.lower() or "ул." in line.lower() or "бул." in line.lower():
                    bureaus.append({"city": current_city, "info": line})
            admissions_data["bureaus"] = bureaus[:20]

        # 4. Regulations (id 187)
        reg_html = self.fetch_url("https://priem.tu-sofia.bg/university/187")
        if reg_html:
            soup = BeautifulSoup(reg_html, 'html.parser')
            p_tags = soup.find_all('p')
            summary = "\n\n".join([normalize_bulgarian_text(p.get_text()) for p in p_tags if len(p.get_text().strip()) > 30][:10])
            admissions_data["regulations_summary"] = summary

        self.knowledge_base["admissions"] = admissions_data
        print(f"[PRIEM] Admissions mapped: {len(admissions_data['calendar_2026'])} calendar entries, fees, bureaus.")

    def crawl_main_entities(self):
        """Scrapes tu-sofia.bg for faculties, colleges, and divisions."""
        # 1. Faculties list
        faculties_html = self.fetch_url("https://tu-sofia.bg/bg/faculties")
        faculty_urls = []
        if faculties_html:
            soup = BeautifulSoup(faculties_html, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/bg/faculties/' in href and href != '/bg/faculties/':
                    faculty_urls.append(href)
        
        faculty_urls = sorted(list(set(faculty_urls)))
        print(f"[MAIN] Discovered {len(faculty_urls)} faculty URLs to crawl.")

        for f_url in faculty_urls:
            full_url = f"https://tu-sofia.bg{f_url}" if f_url.startswith('/') else f_url
            time.sleep(0.15)
            page_html = self.fetch_url(full_url)
            if not page_html:
                continue

            stitched_soup = self.parser.stitch_rsc_dom(page_html)
            title, markdown_content = self.parser.parse_page_to_markdown(page_html, base_url="https://tu-sofia.bg")

            # Extract leadership (Dean, Vice Deans, Departments, Building, Phone, Email)
            clean_text = stitched_soup.get_text(separator=' | ')
            
            # Extract Dean info
            dean_match = re.search(r'Декан\s*\|\s*([^|]+)\s*\|\s*([^|]+)', clean_text)
            dean_name = f"{dean_match.group(1).strip()} {dean_match.group(2).strip()}" if dean_match else ""
            
            slug = f_url.split('/')[-1]
            slug_meta = SLUG_TO_FACULTY.get(slug)
            if slug_meta:
                name_bg = slug_meta["name_bg"]
                name_en = slug_meta["name_en"]
                acronym_code = slug_meta["acronym"]
            else:
                name_bg = title.replace(" | Технически университет - София", "").strip()
                acronym_info = resolve_acronym_or_alias(title)
                acronym_code = acronym_info["code"] if acronym_info else ""
                name_en = acronym_info["full_en"] if acronym_info else transliterate_to_latin(title)

            # Building, Floor and Cabinet
            loc_match = re.search(r'Блок\s*:\s*\|\s*(\d+)\s*\|\s*Етаж\s*:\s*\|\s*(\d+)\s*\|\s*([0-9A-Za-zА-Яа-я\-]+)', clean_text)
            if loc_match:
                block = f"Блок {loc_match.group(1)}"
                cabinet = f"Етаж {loc_match.group(2)}, Кабинет {loc_match.group(3)}"
            else:
                block_match = re.search(r'Блок\s*:\s*\|\s*(\d+)', clean_text)
                block = f"Блок {block_match.group(1)}" if block_match else "Кампус ТУ-София"
                cabinet = ""

            # Phone & Email
            phone_match = re.search(r'02\s*965\s*\d{4}', clean_text)
            phone = phone_match.group(0) if phone_match else ""

            email_match = re.search(r'[\w\.-]+@tu-sofia\.bg', clean_text)
            email = email_match.group(0) if email_match else ""

            # Departments (Катедри)
            departments = []
            for a in stitched_soup.find_all('a', href=True):
                if '/bg/departments/' in a['href']:
                    d_title = normalize_bulgarian_text(a.get_text())
                    if d_title and d_title not in departments:
                        departments.append(d_title)
                        
            dept_matches = re.findall(r'катедра\s*[„"“]([^"”]+)[„"”]', clean_text, re.IGNORECASE)
            for d in dept_matches:
                d_clean = normalize_bulgarian_text(d)
                if len(d_clean) > 3 and d_clean not in departments:
                    departments.append(d_clean)

            # Specialties / Programs
            specialties = []
            for a in stitched_soup.find_all('a', href=True):
                if '/bg/specialty/' in a['href']:
                    s_title = normalize_bulgarian_text(a.get_text())
                    if s_title and s_title not in specialties:
                        specialties.append(s_title)

            # Cross-reference with ECTS curricula
            ects_keyword_map = {
                "ФКСТ": "компютърни",
                "ФА": "автоматика",
                "ФЕТТ": "електронна техника",
                "ЕФ": "електротехнически",
                "ЕМФ": "енергомашиностроителен",
                "МФ": "машиностроителен факултет",
                "СФ": "стопански",
                "ФТ": "транспорта",
                "ФТК": "телекомуникации",
                "ФПМИ": "приложна математика",
                "ФаГИОПМ": "германско",
                "ФФИО": "френско",
                "ФАИО": "английско",
                "ФИТ": "индустриални",
                "ФЕА": "електроника и автоматика",
                "ФМУ": "машиностроене и уредостроене",
                "ИПФ": "инженерно-педагогически"
            }
            curricula_match = None
            kw = ects_keyword_map.get(acronym_code, "").lower()
            if kw:
                for curr in self.knowledge_base["curricula"]:
                    if kw in curr["faculty_name"].lower():
                        curricula_match = curr
                        break

            faculty_entry = {
                "name_bg": name_bg,
                "name_en": name_en,
                "acronym": acronym_code,
                "url": full_url,
                "slug": slug,
                "dean": dean_name,
                "block": block,
                "cabinet": cabinet,
                "phone": phone,
                "email": email,
                "departments": departments,
                "specialties": specialties,
                "ects_data": curricula_match,
                "keywords": extract_keywords(name_bg + " " + " ".join(departments) + " " + " ".join(specialties)),
                "markdown_file": f"knowledge/faculties/{f_url.split('/')[-1]}.md"
            }
            self.knowledge_base["faculties"].append(faculty_entry)

            # Save individual Markdown
            md_path = os.path.join(self.knowledge_dir, "faculties", f"{f_url.split('/')[-1]}.md")
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# {faculty_entry['name_bg']}\n\n")
                f.write(f"**Английско наименование**: {name_en}\n")
                if acronym_code:
                    f.write(f"**Акроним / Код**: {acronym_code}\n")
                f.write(f"**Официален URL**: {full_url}\n\n")
                f.write("## Ръководство и Контакти\n")
                f.write(f"- **Декан**: {dean_name or 'Н/А'}\n")
                f.write(f"- **Локация**: {block or 'Кампус ТУ-София'}, Кабинет: {cabinet or 'Н/А'}\n")
                f.write(f"- **Телефон**: {phone or 'Централа 02 965 21 11'}\n")
                f.write(f"- **Email**: {email or 'delovodstvo@tu-sofia.bg'}\n\n")
                if departments:
                    f.write("## Катедри\n")
                    for d in departments:
                        f.write(f"- Катедра „{d}“\n")
                    f.write("\n")
                if curricula_match and curricula_match.get("bachelor_programs"):
                    f.write("## Учебни планове и Специалности (ECTS)\n")
                    for prog in curricula_match["bachelor_programs"][:10]:
                        f.write(f"- [{prog['title']}]({prog['url']})\n")
                    f.write("\n")
                f.write("## Описание и Профил\n\n")
                f.write(markdown_content)

            self.site_map["categories"]["faculties"].append({
                "title": faculty_entry["name_bg"],
                "acronym": acronym_code,
                "url": full_url
            })

        # 2. Colleges & Divisions
        for category, cat_url in [("colleges", "/bg/colleges"), ("divisions", "/bg/divisions")]:
            html = self.fetch_url(f"https://tu-sofia.bg{cat_url}")
            if not html:
                continue
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if cat_url in href and href != cat_url:
                    full_u = f"https://tu-sofia.bg{href}"
                    time.sleep(0.15)
                    sub_html = self.fetch_url(full_u)
                    if sub_html:
                        sub_title, sub_md = self.parser.parse_page_to_markdown(sub_html, base_url="https://tu-sofia.bg")
                        sub_entry = {
                            "title": sub_title.replace(" | Технически университет - София", "").strip(),
                            "url": full_u,
                            "slug": href.split('/')[-1],
                            "markdown_file": f"knowledge/{category}/{href.split('/')[-1]}.md"
                        }
                        self.knowledge_base.setdefault(category, []).append(sub_entry)
                        self.site_map["categories"].setdefault(category, []).append(sub_entry)

                        sub_file = os.path.join(self.knowledge_dir, category, f"{href.split('/')[-1]}.md")
                        os.makedirs(os.path.dirname(sub_file), exist_ok=True)
                        with open(sub_file, 'w', encoding='utf-8') as sf:
                            sf.write(f"# {sub_entry['title']}\n\n**URL**: {full_u}\n\n{sub_md}")

    def crawl_services_and_contacts(self):
        """Scrapes contacts, student dormitories (ПССО), student council, and phone directory."""
        # 1. Contacts
        contacts_html = self.fetch_url("https://tu-sofia.bg/bg/contacts")
        if contacts_html:
            _, md = self.parser.parse_page_to_markdown(contacts_html)
            with open(os.path.join(self.knowledge_dir, "contacts", "contacts.md"), 'w', encoding='utf-8') as f:
                f.write("# Контакти на Технически университет - София\n\n" + md)

        # 2. Services: Dormitories (ПССО) & Student Life
        dorm_info = {
            "name": "Поделение „Студентски столове и общежития“ (ПССО)",
            "location": "Студентски град, София, бл. 1, бл. 2, бл. 3, бл. 4, бл. 8, бл. 9, бл. 10, бл. 11, бл. 12, бл. 14, бл. 15, бл. 16, бл. 21, бл. 22",
            "capacity": "Над 6000 места за студенти и докторанти",
            "contacts": "Телефон: 02 965 3111, Email: psso@tu-sofia.bg",
            "conditions": "Класирането се извършва въз основа на успех и социален статус съгласно Правилника за настаняване."
        }
        self.knowledge_base["services"]["dormitories"] = dorm_info
        with open(os.path.join(self.knowledge_dir, "services", "dormitories.md"), 'w', encoding='utf-8') as f:
            f.write("# Студентски столове и общежития (ПССО) - ТУ-София\n\n")
            f.write(f"- **Локация**: {dorm_info['location']}\n")
            f.write(f"- **Капацитет**: {dorm_info['capacity']}\n")
            f.write(f"- **Контакти**: {dorm_info['contacts']}\n")
            f.write(f"- **Условия за настаняване**: {dorm_info['conditions']}\n")

        # 3. Student Council
        sc_info = {
            "name": "Студентски съвет при ТУ-София",
            "location": "Блок 2, стая 2101",
            "phone": "02 965 3218",
            "email": "sc@tu-sofia.bg",
            "website": "https://students.tu-sofia.bg"
        }
        self.knowledge_base["services"]["student_council"] = sc_info
        with open(os.path.join(self.knowledge_dir, "services", "student_council.md"), 'w', encoding='utf-8') as f:
            f.write("# Студентски съвет при ТУ-София\n\n")
            f.write(f"- **Кабинет**: {sc_info['location']}\n")
            f.write(f"- **Телефон**: {sc_info['phone']}\n")
            f.write(f"- **Email**: {sc_info['email']}\n")
            f.write(f"- **Сайт**: {sc_info['website']}\n")

    def export_results(self):
        """Exports data/tu_sofia_kb.json, data/tu_sofia_map.json and main knowledge summaries."""
        # 1. Export Knowledge Base JSON
        kb_path = os.path.join(self.data_dir, "tu_sofia_kb.json")
        with open(kb_path, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge_base, f, ensure_ascii=False, indent=2)
        print(f"[EXPORT] Successfully saved {kb_path} ({os.path.getsize(kb_path)} bytes)")

        # 2. Build Site Map Nodes
        for f in self.knowledge_base["faculties"]:
            self.site_map["nodes"].append({
                "id": f["slug"],
                "type": "faculty",
                "label": f["name_bg"],
                "acronym": f["acronym"],
                "url": f["url"],
                "details": f"Декан: {f['dean']} | {f['block']}, Каб. {f['cabinet']}"
            })

        for c in self.knowledge_base["colleges"]:
            self.site_map["nodes"].append({
                "id": c["slug"],
                "type": "college",
                "label": c["title"],
                "url": c["url"]
            })

        self.site_map["nodes"].append({
            "id": "priem-2026",
            "type": "admissions",
            "label": "Прием 2026/2027",
            "url": "https://priem.tu-sofia.bg",
            "details": f"{len(self.knowledge_base['admissions']['calendar_2026'])} ключови календарни дати и такси"
        })

        self.site_map["nodes"].append({
            "id": "ects-curricula",
            "type": "curricula",
            "label": "ЕСНТК / Учебни планове (ECTS)",
            "url": "https://ects.tu-sofia.bg",
            "details": f"{len(self.knowledge_base['curricula'])} каталогизирани факултетни пакета"
        })

        map_path = os.path.join(self.data_dir, "tu_sofia_map.json")
        with open(map_path, 'w', encoding='utf-8') as f:
            json.dump(self.site_map, f, ensure_ascii=False, indent=2)
        print(f"[EXPORT] Successfully saved {map_path} ({os.path.getsize(map_path)} bytes)")

        # 3. Create Root Admissions Markdown file
        with open(os.path.join(self.knowledge_dir, "admissions", "calendar_2026.md"), 'w', encoding='utf-8') as f:
            f.write("# Календарен график за кандидатстудентска кампания 2026/2027 - ТУ-София\n\n")
            f.write("| Дейност | Срок |\n|---|---|\n")
            for item in self.knowledge_base["admissions"]["calendar_2026"]:
                f.write(f"| {item['activity']} | {item['deadline']} |\n")

        with open(os.path.join(self.knowledge_dir, "admissions", "fees.md"), 'w', encoding='utf-8') as f:
            f.write("# Такси за кандидатстване и обучение в ТУ-София (2026/2027)\n\n")
            for k, v in self.knowledge_base["admissions"]["fees"].items():
                f.write(f"- **{k}**: {v}\n")

        print("=== Knowledge Base & Semantic Map Generation Complete! ===")


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    crawler = TUSofiaCrawler(output_dir=root_dir)
    crawler.crawl_all()
