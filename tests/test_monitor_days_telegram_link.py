"""Monitor SVG web badges and Telegram append-only URL regressions."""
import ast
from pathlib import Path
import unittest
from typing import Optional, Tuple, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
URL = "https://flask-393d.onrender.com/admin/container-excel"
REPORT = "https://flask-393d.onrender.com/monitor/report?api_key=TESTTOKEN"


def render_monitor(web):
    templates = ROOT / "templates"
    env = Environment(loader=FileSystemLoader(str(templates)), autoescape=select_autoescape(["html", "xml"]))
    template = env.get_template("reports/iti_telegram_report.html")

    def container(code, days, remaining, matched=False):
        return {
            "contenedor": code,
            "folio": "166" if matched else "-",
            "fecha_entrega": "27/10/2026 · 18:18",
            "estado": "VISADO",
            "manual_days": days, "excel_days": None,
            "timer": {"remaining": remaining} if remaining is not None else None,
            "delivery_risk": 0 if matched else None,
        }

    return template.render(
        company_name="XINGWANG", generated_date="27/10/2026",
        generated_time="05:28", total_count=3, matched_count=1, unmatched_count=2,
        show_matched=True, show_unmatched=True,
        matched_groups=[{"nave": "MANZANILLO EXPRESS", "count": 1,
                         "eta": "24/10/2026", "ship_timer": {"remaining": 11},
                         "web_ship_remaining": 18,
                         "contenedores": [container("TLLU5363704", 21, 18, True)]}],
        unmatched_groups=[{"nave": "MSC TORONTO VIII", "count": 2,
                           "eta": "24/10/2026", "ship_timer": {"remaining": 11},
                           "web_ship_remaining": -2,
                           "contenedores": [container("HLBU9941809", 14, 3),
                                            container("TEMU7551438", 21, -2)]}],
        web_report_only=web, api_key="TESTTOKEN" if web else "",
        result_hash="TESTHASH",
    )


def telegram_function():
    file = ROOT / "services" / "monitor_service.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "send_notification_telegram")
    ns = {
        "Optional": Optional, "Tuple": Tuple, "Dict": Dict, "List": List,
        "normalize_telegram_mode": lambda x: x,
        "normalize_telegram_max_rows": lambda x: x,
        "_build_telegram_text_message": lambda **kw: "ORIGINAL TELEGRAM BODY",
        "_build_telegram_image_caption": lambda *args: "ORIGINAL TELEGRAM PHOTO CAPTION",
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(file), "exec"), ns)
    return ns


class MonitorBadgesTests(unittest.TestCase):
    def test_web_icons_and_signed_remaining_without_days_suffix(self):
        html = render_monitor(True)
        self.assertIn('class="web-days"', html)
        self.assertIn('class="ft-total"', html)
        self.assertIn("剩餘 18 天", html)
        self.assertIn("逾期 2 天", html)
        self.assertIn("ft-safe", html)
        self.assertIn("ft-soon", html)
        self.assertIn("ft-danger", html)
        self.assertNotIn("21d", html)
        self.assertNotIn("14d", html)
        self.assertNotIn('class="timer-mini timer-red"', html)
        self.assertNotIn("Plazo referencial 14 días", html)
    def test_matched_container_and_svg_are_one_line_on_mobile(self):
        # CSS is scoped to WEB matched rows, leaving Telegram PNG unchanged.
        source = (ROOT / "templates" / "reports" / "iti_telegram_report.html").read_text(encoding="utf-8-sig")
        self.assertIn(".web-days .v-card.matched .t-container{white-space:nowrap}", source)
        self.assertIn(".web-days .v-card.matched table{table-layout:fixed}", source)
        self.assertIn(".web-days .v-card.matched .t-container .ft-total", source)
        html = render_monitor(True)
        self.assertIn("TLLU5363704", html)
        self.assertIn('class="ft-total"', html)

    def test_excel_import_entry_is_svg_only_and_accessible(self):
        web = render_monitor(True)
        self.assertIn('href="/admin/container-excel"', web)
        self.assertIn('aria-label="匯入 Excel 貨櫃資料"', web)
        self.assertIn('class="excel-entry"', web)
        entry = web.split('class="excel-entry"', 1)[1].split("</a>", 1)[0]
        self.assertIn('<svg ', entry)
        self.assertIn('M18 3v10', entry)
        self.assertNotIn(">Excel 匯入", entry)
        snapshot = render_monitor(False)
        self.assertNotIn('class="excel-entry"', snapshot)

    def test_desktop_fifth_column_fits_matched_card(self):
        # The desktop report is max-width 520px with 24px side padding.
        # Old auto-layout pushed the hourglass column outside the green card.
        import re
        source = (ROOT / "templates" / "reports" / "iti_telegram_report.html").read_text(encoding="utf-8-sig")
        self.assertIn(".web-days .v-card.matched table{width:100%;table-layout:fixed}", source)
        cols = ["folio", "fecha", "estado", "remaining"]
        sizes = []
        for col in cols:
            match = re.search(r"\.web-days \.v-card\.matched \.col-" + col + r"\{width:(\d+)px\}", source)
            self.assertIsNotNone(match, col)
            sizes.append(int(match.group(1)))
        # Leave meaningful room for 11-digit container code + total-days SVG.
        self.assertGreaterEqual(520 - 48 - sum(sizes), 170)
        self.assertIn(".web-days .v-card.matched .t-container{font-size:11px;letter-spacing:0;white-space:nowrap}", source)
        self.assertIn(".web-days .v-card.matched .t-fecha{font-size:10px;letter-spacing:0;white-space:nowrap}", source)

    def test_telegram_image_markup_remains_original(self):
        html = render_monitor(False)
        self.assertIn("21d", html)
        self.assertIn("14d", html)
        self.assertNotIn('class="ft-total"', html)
        self.assertNotIn('class="web-days"', html)
        self.assertIn("Plazo referencial 14 días", html)
        self.assertNotIn("Excel 匯入</a>", html)
    def test_photo_notification_adds_one_url_below_existing(self):
        ns = telegram_function()
        sent = []
        ns["send_telegram_photo"] = lambda token, chat, image, caption="": (sent.append(caption) or True, "")
        ns["_render_telegram_table_image"] = lambda **kw: ([b"png"], "")
        ns["send_telegram_message"] = lambda *args: (True, "")
        ok, msg = ns["send_notification_telegram"](
            "BOT", "CHAT", [{"codigo": "TEST"}],
            {"company_name": "XINGWANG", "telegram_mode": "image"}, REPORT)
        self.assertTrue(ok, msg)
        self.assertEqual(len(sent), 1)
        self.assertIn("ORIGINAL TELEGRAM PHOTO CAPTION", sent[0])
        self.assertIn(REPORT, sent[0])
        self.assertIn(URL, sent[0])
        self.assertIn("設定／匯入免箱天數", sent[0])
        self.assertLess(sent[0].index(REPORT), sent[0].index(URL))
        self.assertEqual(sent[0].count(URL), 1)
        self.assertLessEqual(len(sent[0]), 1024)
    def test_text_and_photo_fallback_receive_url(self):
        ns = telegram_function()
        received = []
        ns["send_telegram_message"] = lambda token, chat, body: (received.append(body) or True, "")
        ns["_render_telegram_table_image"] = lambda **kw: ([], "image error")
        for mode in ("text", "image", "both"):
            ok, msg = ns["send_notification_telegram"](
                "BOT", "CHAT", [{"codigo": "TEST"}],
                {"company_name": "XINGWANG", "telegram_mode": mode}, REPORT)
            self.assertTrue(ok, (mode, msg))
            self.assertEqual(received[-1].count(URL), 1)
            self.assertIn("ORIGINAL TELEGRAM BODY", received[-1])
            if mode != "both": self.assertIn(REPORT, received[-1])


if __name__ == "__main__":
    unittest.main()
