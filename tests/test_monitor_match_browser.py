"""Headless browser regression: no clipped Matched hourglass on desktop.

Render the actual Jinja report from fixtures and verify CSS layout bounds.
"""
import unittest
from test_monitor_days_telegram_link import render_monitor
from playwright.sync_api import sync_playwright


class MatchedReportLayoutTests(unittest.TestCase):
    def test_hourglass_inside_matched_card_at_desktop_and_tablet_widths(self):
        rendered = render_monitor(True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                for width in (431, 460, 551, 900):
                    with self.subTest(viewport=width):
                        page = browser.new_page(viewport={"width": width, "height": 700})
                        try:
                            page.set_content(rendered, wait_until="domcontentloaded")
                            positions = page.evaluate("""() => {
                                const card = document.querySelector('.v-card.matched');
                                const inline = card.querySelector('.desktop-inline-remaining');
                                const fifth = card.querySelector('.t-remaining');
                                const table = card.querySelector('table');
                                const lastStatus = card.querySelector('.t-estado');
                                const get = el => el.getBoundingClientRect();
                                return {
                                    cardRight: get(card).right,
                                    tableRight: get(table).right,
                                    inlineRight: get(inline).right,
                                    statusRight: get(lastStatus).right,
                                    inlineDisplay: getComputedStyle(inline).display,
                                    fifthDisplay: getComputedStyle(fifth).display,
                                    inlineWidth: get(inline).width
                                };
                            }""")
                            self.assertNotEqual(positions["inlineDisplay"], "none", positions)
                            self.assertEqual(positions["fifthDisplay"], "none", positions)
                            self.assertGreater(positions["inlineWidth"], 10, positions)
                            self.assertLessEqual(positions["tableRight"], positions["cardRight"] + .5, positions)
                            self.assertLessEqual(positions["statusRight"], positions["cardRight"] + .5, positions)
                            self.assertLessEqual(positions["inlineRight"], positions["cardRight"] - 1, positions)
                        finally:
                            page.close()
            finally:
                browser.close()

    def test_phone_retains_original_fifth_column(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 390, "height": 700})
                page.set_content(render_monitor(True), wait_until="domcontentloaded")
                displays = page.evaluate("""() => {
                    const card = document.querySelector('.v-card.matched');
                    return {
                        inline: getComputedStyle(card.querySelector('.desktop-inline-remaining')).display,
                        fifth: getComputedStyle(card.querySelector('.t-remaining')).display
                    }
                }""")
                self.assertEqual(displays["inline"], "none")
                self.assertNotEqual(displays["fifth"], "none")
                page.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
