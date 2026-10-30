"""Regression: the standalone crawler must not bootstrap ORDER/B2 at import time."""
import os
import subprocess
import sys
import unittest


class CrawlerPackageIsolationTest(unittest.TestCase):
    def test_crawler_imports_do_not_load_order_modules(self):
        code = """
import sys
import services
import blueprints
from services import container_iti_service
from blueprints.automation_hub import automation_hub_bp
from blueprints.aduana_monitor import aduana_bp
loaded = set(sys.modules)
assert not any(name.startswith('services.order_') for name in loaded), sorted(
    name for name in loaded if name.startswith('services.order_'))
assert not any(name.startswith('blueprints.b2_test_bp') for name in loaded)
assert not any(name.startswith('blueprints.user_auth_bp') for name in loaded)
assert 'blueprints.automation_hub' in loaded
assert 'blueprints.aduana_monitor' in loaded
assert 'services.container_iti_service' in loaded
"""
        env = os.environ.copy()
        env["XINGWANG_SERVICE_ROLE"] = "CRAWLER"
        env["TOWN_STANDALONE_SERVICE"] = "0"
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            "Crawler import isolation failed:\\n" + result.stdout + result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
