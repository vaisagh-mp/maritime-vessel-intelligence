from django.test import TestCase

from .models import Port


class PortModelTests(TestCase):
    def test_str_includes_un_locode(self):
        port = Port.objects.create(
            name="Fujairah",
            un_locode="AEFJR",
            latitude=25.12,
            longitude=56.34,
            anchorage_latitude=25.15,
            anchorage_longitude=56.40,
            geofence_radius_km=45,
        )
        self.assertIn("AEFJR", str(port))
        self.assertTrue(port.active)
