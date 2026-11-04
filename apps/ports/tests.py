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


class SetupPilotPortsCommandTests(TestCase):
    def _port(self, name, locode, active=True):
        return Port.objects.create(
            name=name, un_locode=locode, latitude=1, longitude=1,
            anchorage_latitude=1, anchorage_longitude=1, geofence_radius_km=10, active=active,
        )

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("setup_pilot_ports", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        rashid = self._port("Port Rashid", "AEPRA")
        sg = self._port("Singapore", "SGSIN")
        self._run()
        rashid.refresh_from_db()
        sg.refresh_from_db()
        self.assertEqual(rashid.un_locode, "AEPRA")
        self.assertTrue(rashid.active)
        self.assertIsNone(sg.marinetraffic_port_id)

    def test_apply_fixes_locode_and_limits_active_ports(self):
        from apps.vessels.models import Vessel

        rashid = self._port("Port Rashid", "AEPRA")
        sg = self._port("Singapore", "SGSIN", active=False)
        fj = self._port("Fujairah", "AEFJR")
        Vessel.objects.create(mmsi="211000001", name="A", imo="0")
        Vessel.objects.bulk_create([Vessel(mmsi="211000002", name="B", imo="0")])  # bypasses save()
        buoy = Vessel.objects.create(mmsi="994196109", name="BUOY")

        self._run("--apply")

        for p in (rashid, sg, fj):
            p.refresh_from_db()
        self.assertEqual(rashid.un_locode, "AEDXB")
        self.assertFalse(rashid.active)
        self.assertTrue(sg.active)
        self.assertTrue(fj.active)
        self.assertEqual(sg.marinetraffic_port_id, 290)
        self.assertEqual(fj.marinetraffic_port_id, 790)
        self.assertFalse(Vessel.objects.filter(imo="0").exists())
        self.assertTrue(Vessel.objects.filter(pk=buoy.pk).exists())  # junk reported, never deleted

    def test_apply_is_idempotent_and_handles_locode_collision(self):
        self._port("Dubai", "AEDXB")
        rashid = self._port("Port Rashid", "AEPRA")
        self._run("--apply")
        self._run("--apply")
        rashid.refresh_from_db()
        self.assertEqual(rashid.un_locode, "AEPRA")  # collision: left for manual resolution
