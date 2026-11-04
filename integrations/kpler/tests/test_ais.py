"""Unit tests for Kpler AIS stub."""
from django.test import SimpleTestCase

from integrations.kpler.ais import fetch_ais_latest


class AISStubTests(SimpleTestCase):
    def test_fetch_ais_latest_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            fetch_ais_latest("some_port")
        self.assertIn("Implemented in Step 10", str(ctx.exception))
