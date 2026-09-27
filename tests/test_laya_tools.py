"""
Automated Test Suite for Laya AI TU Sofia Tools.
Verifies Bulgarian NLP disambiguation, acronym resolution, admissions queries,
faculty lookups, and model-to-model JSON payloads.
"""

import os
import sys
import unittest
import json

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
    LAYA_TOOLS_SCHEMAS
)

class TestLayaTools(unittest.TestCase):

    def test_acronym_search_fkst(self):
        """Test searching for FKST in Cyrillic."""
        results = search_tu_sofia("ФКСТ", limit=3)
        self.assertGreater(len(results), 0)
        top = results[0]
        self.assertEqual(top["acronym"], "ФКСТ")
        self.assertIn("компютърни системи", top["title"].lower())
        self.assertIn("Румен Трифонов", top["snippet"])

    def test_latin_acronym_search(self):
        """Test searching for FKST using English Latinitsa."""
        results = search_tu_sofia("FKST", limit=3)
        self.assertGreater(len(results), 0)
        top = results[0]
        self.assertEqual(top["acronym"], "ФКСТ")

    def test_admissions_fee_search(self):
        """Test searching for admissions fees."""
        results = search_tu_sofia("такси за кандидатстване", limit=3)
        self.assertGreater(len(results), 0)
        types = [r["type"] for r in results]
        self.assertIn("admissions", types)

    def test_get_faculty_info_fkst(self):
        """Test structured faculty extraction for FKST."""
        info = get_faculty_info("ФКСТ")
        self.assertEqual(info["status"], "success")
        self.assertEqual(info["code"], "ФКСТ")
        self.assertEqual(info["leadership"]["dean"], "проф. д-р инж. Румен Трифонов")
        self.assertGreater(len(info["departments"]), 0)

    def test_get_faculty_info_fa(self):
        """Test structured faculty extraction for Faculty of Automatics."""
        info = get_faculty_info("Автоматика")
        self.assertEqual(info["status"], "success")
        self.assertEqual(info["code"], "ФА")
        self.assertEqual(info["leadership"]["dean"], "доц. д-р инж. Цоньо Славов")

    def test_get_faculty_info_fa_acronym(self):
        """Test that FA acronyms do not accidentally route to FPMI."""
        for q in ["ФА", "FA", "fa"]:
            info = get_faculty_info(q)
            self.assertEqual(info["status"], "success")
            self.assertEqual(info["code"], "ФА", f"Failed for query {q}")
            self.assertEqual(info["leadership"]["dean"], "доц. д-р инж. Цоньо Славов")

    def test_shlokavica_resolution(self):
        """Test Bulgarian-English shlokavica faculty and leadership resolution."""
        from crawler.bulgarian_nlp import resolve_acronym_or_alias
        
        m_fkst = resolve_acronym_or_alias("koi e shef na fkst")
        self.assertIsNotNone(m_fkst)
        self.assertEqual(m_fkst["code"], "ФКСТ")

        m_fa = resolve_acronym_or_alias("koi e dekan na fa")
        self.assertIsNotNone(m_fa)
        self.assertEqual(m_fa["code"], "ФА")

        m_sf = resolve_acronym_or_alias("koi e shef na stopanski fakultet")
        self.assertIsNotNone(m_sf)
        self.assertEqual(m_sf["code"], "СФ")

        m_fpmi = resolve_acronym_or_alias("koi e shefa na fpm")
        self.assertIsNotNone(m_fpmi)
        self.assertEqual(m_fpmi["code"], "ФПМИ")

    def test_admissions_calendar(self):
        """Test 2026 admissions calendar deadlines."""
        cal = get_admissions_info(topic="calendar", year=2026)
        self.assertEqual(cal["status"], "success")
        self.assertGreater(len(cal["deadlines"]), 0)
        # Check for 2026 date in deadlines
        has_2026 = any("2026" in d.get("deadline", "") for d in cal["deadlines"])
        self.assertTrue(has_2026)

    def test_admissions_fees(self):
        """Test official fee structure."""
        fees = get_admissions_info(topic="fees")
        self.assertEqual(fees["status"], "success")
        self.assertIn("exam_fee", fees["fees_structure"])
        self.assertIn("30 евро", fees["fees_structure"]["exam_fee"])

    def test_curriculum_fa_bachelor(self):
        """Test ECTS curricula lookup for Faculty Automatics."""
        curr = get_curriculum(faculty="ФА", degree="bachelor")
        self.assertEqual(curr["status"], "success")
        self.assertEqual(curr["degree"], "bachelor")
        self.assertGreater(curr["programs_count"], 0)
        self.assertTrue(any("pdf" in p.get("url", "").lower() for p in curr["study_plans"]))

    def test_contact_rectorate(self):
        """Test rectorate contact lookup."""
        contact = get_contact_info("ректор")
        self.assertEqual(contact["status"], "success")
        self.assertEqual(contact["category"], "rectorate")
        self.assertIn("Георги Венков", contact["contacts"]["rector"])

    def test_dormitories_service(self):
        """Test student dormitories contact lookup."""
        contact = get_contact_info("общежития")
        self.assertEqual(contact["status"], "success")
        self.assertEqual(contact["category"], "dormitories")
        self.assertIn("Студентски град", contact["contacts"]["location"])

    def test_model_to_model_envelope(self):
        """Test the M2M serialization envelope."""
        fac = get_faculty_info("ФКСТ")
        envelope = format_tool_payload_for_model(
            tool_name="get_faculty_info",
            result=fac,
            destination_model="Gemini-2.5-Flash"
        )
        self.assertEqual(envelope["source"], "LayaTUInfo/v1.0")
        self.assertEqual(envelope["target_model"], "Gemini-2.5-Flash")
        self.assertEqual(envelope["payload"]["code"], "ФКСТ")

    def test_json_schemas(self):
        """Validate JSON schemas exported for tool use / function calling."""
        self.assertEqual(len(LAYA_TOOLS_SCHEMAS), 6)
        tool_names = [t["name"] for t in LAYA_TOOLS_SCHEMAS]
        self.assertIn("search_tu_sofia", tool_names)
        self.assertIn("get_faculty_info", tool_names)
        self.assertIn("get_admissions_info", tool_names)
        self.assertIn("get_curriculum", tool_names)


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    unittest.main()
