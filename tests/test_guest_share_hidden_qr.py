"""Regression checks: hidden QR action is client-side and never changes ORDER sharing."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
PAGE=(ROOT/"templates/tracking/customer_share_public.html").read_text("utf-8")
JS=(ROOT/"static/js/order_guest_qrcode.min.js").read_text("utf-8")


class GuestShareHiddenQRTests(unittest.TestCase):
    def test_name_only_is_secret_long_press_target(self):
        self.assertEqual(PAGE.count('class="guest-qr-trigger"'),2)
        self.assertIn("setTimeout(openQr,1500)",PAGE)
        self.assertIn("pointermove",PAGE)
        self.assertIn("pointercancel",PAGE)
        self.assertIn("pointerup",PAGE)
        self.assertIn("contextmenu",PAGE)
        self.assertIn("-webkit-touch-callout:none",PAGE)

    def test_no_visible_control_until_opened(self):
        self.assertIn(".guest-qr-modal{position:fixed;inset:0;z-index:2500;display:none",PAGE)
        self.assertIn("modal.classList.add('open')",PAGE)
        self.assertIn("modal.classList.remove('open')",PAGE)
        self.assertIn("event.key==='Escape'",PAGE)
        self.assertIn("aria-hidden=\"true\"",PAGE)

    def test_qr_encodes_same_public_url_not_token_or_admin(self):
        self.assertIn("location.origin+location.pathname+location.search",PAGE)
        self.assertIn("new QRCode(qr,{text:url",PAGE)
        self.assertNotIn("fetch('/api",PAGE)
        self.assertNotIn("navigator.sendBeacon",PAGE)
        self.assertNotIn("window.open(",PAGE)

    def test_local_qr_library_and_license(self):
        self.assertIn("url_for('static', filename='js/order_guest_qrcode.min.js')",PAGE)
        self.assertIn("var QRCode;",JS)
        self.assertTrue((ROOT/"static/js/qrcodejs.LICENSE.txt").is_file())
        self.assertIn("Copyright (c) 2012 davidshimjs",(ROOT/"static/js/qrcodejs.LICENSE.txt").read_text("utf-8"))

    def test_unchanged_public_wall_behaviors(self):
        self.assertIn('id="shareLangButton"',PAGE)
        self.assertIn('onclick="openOrder(',PAGE)
        self.assertIn("function closeOrder()",PAGE)
        self.assertIn('id="viewer"',PAGE)


if __name__=="__main__":
    unittest.main()
