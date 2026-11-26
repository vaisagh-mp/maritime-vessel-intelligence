from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import Company
from apps.opportunities.models import Opportunity
from apps.outreach import service
from apps.outreach.models import EmailLog, EmailTemplate
from apps.ports.models import Port
from apps.relationships.models import VesselRelationship
from apps.vessels.models import Vessel

PREVIEW, SEND, LOG, TEMPLATES = ("/api/v1/outreach/preview/", "/api/v1/outreach/send/",
                                 "/api/v1/outreach/log/", "/api/v1/outreach/templates/")


class OutreachBase(TestCase):
    def setUp(self):
        self.port = Port.objects.create(name="Fujairah", un_locode="AEFJR", latitude=1, longitude=1, anchorage_latitude=1,
                                        anchorage_longitude=1, geofence_radius_km=5, marinetraffic_port_id=790, active=True)
        self.vessel = Vessel.objects.create(imo="9308766", mmsi="500000001", name="MT TESTER", vessel_type="Tanker", grt=42000)
        Opportunity.objects.create(vessel=self.vessel, port=self.port, zone="72h", score=70,
                                   eta=timezone.now() + timedelta(days=2))
        self.company = Company.objects.create(name="Acme Shipping", company_type="manager", email="ops@acme.com", country="Greece")
        self.rel = VesselRelationship.objects.create(vessel=self.vessel, company=self.company, role="technical_manager")
        self.user = User.objects.create_user("asha", "asha@splendour.com", "pw", first_name="Asha", last_name="Rao")
        self.user.groups.add(Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)[0])
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.template = EmailTemplate.objects.create(
            name="T1", kind="first_contact", subject="Services for {{vessel_name}}",
            body="Dear {{company_name}}, {{vessel_name}} arrives at {{port}} on {{eta}}. {{sender_name}}")

    def send(self, **extra):
        data = {"relationship_id": self.rel.id, "template_id": self.template.id,
                "subject": "Hello", "body": "Body text", **extra}
        return self.client.post(SEND, data, format="json")


class RenderTests(OutreachBase):
    def test_placeholders_are_filled_and_unknown_ones_reported(self):
        ctx = service.build_context(self.rel, self.user)
        text, unknown = service.render("{{ company_name }} / {{vessel_name}} / {{port}} / {{role}} / {{nope}}", ctx)
        self.assertEqual(text, "Acme Shipping / MT TESTER / Fujairah / Technical Manager / {{nope}}")
        self.assertEqual(unknown, ["nope"])
        self.assertEqual(ctx["sender_name"], "Asha Rao")

    def test_subject_is_one_line(self):
        self.assertEqual(service.clean_subject("Hi\r\nBcc: x@y.com"), "Hi Bcc: x@y.com")

    def test_address_checks(self):
        self.assertEqual(service.valid_address(" a@b.com "), "a@b.com")
        for bad in ("", "a@b.com, c@d.com", "a@b.com\nbcc:x@y.com", "nope", "a b@c.com"):
            self.assertIsNone(service.valid_address(bad))


class PreviewTests(OutreachBase):
    def test_preview_fills_the_template_and_sends_nothing(self):
        r = self.client.post(PREVIEW, {"relationship_id": self.rel.id, "template_id": self.template.id}, format="json").data
        self.assertEqual(r["to"], "ops@acme.com")
        self.assertEqual(r["subject"], "Services for MT TESTER")
        self.assertIn("arrives at Fujairah on", r["body"])
        self.assertTrue(r["can_send"])
        self.assertEqual(mail.outbox, [])

    def test_company_without_email_cannot_send(self):
        self.company.email = ""
        self.company.save()
        r = self.client.post(PREVIEW, {"relationship_id": self.rel.id, "template_id": self.template.id}, format="json").data
        self.assertFalse(r["can_send"])
        self.assertIn("no valid email", r["reason"])

    def test_hr_mailbox_is_flagged(self):
        self.company.email = "hr@acme.com"
        self.company.save()
        r = self.client.post(PREVIEW, {"relationship_id": self.rel.id, "template_id": self.template.id}, format="json").data
        self.assertTrue(any("HR" in w for w in r["warnings"]))

    def test_inactive_template_is_not_offered(self):
        self.template.active = False
        self.template.save()
        self.assertNotIn(self.template.id, [t["id"] for t in self.client.get(TEMPLATES).data["templates"]])
        resp = self.client.post(PREVIEW, {"relationship_id": self.rel.id, "template_id": self.template.id}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_default_templates_are_seeded_by_the_migration(self):
        self.assertTrue(EmailTemplate.objects.filter(kind="first_contact").exclude(pk=self.template.pk).exists())
        self.assertTrue(EmailTemplate.objects.filter(kind="reminder").exists())


class SendTests(OutreachBase):
    def test_sends_exactly_what_is_on_screen_to_the_company_address(self):
        r = self.send(subject="My subject\nBcc: evil@x.com", body="Edited body")
        self.assertEqual(r.status_code, 200)
        m = mail.outbox[0]
        self.assertEqual((m.to, m.subject, m.body), (["ops@acme.com"], "My subject Bcc: evil@x.com", "Edited body"))
        self.assertEqual(m.reply_to, ["asha@splendour.com"])
        log = EmailLog.objects.get()
        self.assertEqual((log.company, log.vessel, log.sent_by, log.template_name), (self.company, self.vessel, self.user, "T1"))

    def test_the_recipient_cannot_be_chosen_by_the_caller(self):
        self.send(to="someone@else.com", to_email="someone@else.com")
        self.assertEqual(mail.outbox[0].to, ["ops@acme.com"])

    @override_settings(EMAIL_HOST="")
    def test_test_mode_is_recorded_as_test(self):
        r = self.send()
        self.assertEqual(EmailLog.objects.get().status, "test")
        self.assertIn("Test mode", r.data["detail"])

    @override_settings(EMAIL_HOST="smtp.example.com")
    def test_live_mode_is_recorded_as_sent(self):
        self.send()
        self.assertEqual(EmailLog.objects.get().status, "sent")

    def test_unreplaced_placeholders_block_the_send(self):
        r = self.send(body="Dear {{company_name}}")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_empty_subject_or_body_and_no_address(self):
        self.assertEqual(self.send(subject=" ").status_code, 400)
        self.assertEqual(self.send(body="").status_code, 400)
        self.company.email = ""
        self.company.save()
        self.assertEqual(self.send().status_code, 400)

    def test_second_mail_to_the_same_company_and_vessel_needs_confirmation(self):
        self.assertEqual(self.send().status_code, 200)
        again = self.send()
        self.assertEqual((again.status_code, again.data["code"]), (409, "needs_confirm"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.send(confirm=True).status_code, 200)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(OUTREACH_ENABLED=False)
    def test_switch_off(self):
        self.assertEqual(self.send().status_code, 409)
        self.assertEqual(mail.outbox, [])

    @override_settings(OUTREACH_DAILY_LIMIT_PER_USER=1)
    def test_daily_limit(self):
        self.send()
        self.assertEqual(self.send(confirm=True).status_code, 429)

    def test_failed_delivery_is_logged_without_leaking_secrets(self):
        from unittest.mock import patch

        with override_settings(EMAIL_HOST_PASSWORD="s3cret"), patch("django.core.mail.EmailMessage.send", side_effect=OSError("auth failed s3cret")):
            r = self.send()
        self.assertEqual(r.status_code, 502)
        log = EmailLog.objects.get()
        self.assertEqual(log.status, "failed")
        self.assertNotIn("s3cret", log.error + str(r.data))

    def test_bcc_copy(self):
        with override_settings(OUTREACH_BCC="archive@splendour.com, bad address"):
            self.send()
        self.assertEqual(mail.outbox[0].bcc, ["archive@splendour.com"])

    def test_needs_a_role(self):
        self.client.force_authenticate(User.objects.create_user("nobody", "n@x.com", "pw"))
        self.assertIn(self.send().status_code, (401, 403))
        self.assertEqual(mail.outbox, [])


class LogTests(OutreachBase):
    def test_latest_mail_per_company_with_count(self):
        self.send()
        self.send(confirm=True, subject="Second")
        other = Company.objects.create(name="Other", company_type="owner", email="x@other.com")
        EmailLog.objects.create(company=other, vessel=self.vessel, to_email="x@other.com", subject="f", body="b", status="failed")
        rows = self.client.get(LOG, {"vessel": self.vessel.id}).data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["company_id"], rows[0]["subject"], rows[0]["count"], rows[0]["sent_by"]),
                         (self.company.id, "Second", 2, "Asha Rao"))

    def test_vessel_is_required(self):
        self.assertEqual(self.client.get(LOG).status_code, 400)


MANAGE, HISTORY = "/api/v1/outreach/manage/templates/", "/api/v1/outreach/history/"


class ManageTemplatesTests(OutreachBase):
    def test_list_includes_switched_off_templates_and_placeholders(self):
        EmailTemplate.objects.create(name="Off", subject="s", body="b", active=False)
        data = self.client.get(MANAGE).data
        self.assertEqual({t["name"] for t in data["templates"]}, {"T1", "Off", *EmailTemplate.objects.values_list("name", flat=True)})
        self.assertIn("vessel_name", data["placeholders"])
        self.assertEqual(len(data["kinds"]), 3)

    def test_add_change_and_switch_off(self):
        r = self.client.post(MANAGE, {"name": "New one", "kind": "reminder", "subject": "Hi {{vessel_name}}", "body": "Text"}, format="json")
        self.assertEqual(r.status_code, 201)
        pk = r.data["id"]
        r = self.client.patch(f"{MANAGE}{pk}/", {"subject": "Changed", "active": False}, format="json")
        self.assertEqual((r.status_code, r.data["subject"], r.data["active"]), (200, "Changed", False))
        names = [t["name"] for t in self.client.get(TEMPLATES).data["templates"]]
        self.assertNotIn("New one", names)          # a switched-off template is not offered in the Send mail dialog

    def test_validation(self):
        r = self.client.post(MANAGE, {"name": "", "subject": "s\nBcc: x@y.com", "body": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("name", r.data["errors"])
        self.assertIn("body", r.data["errors"])
        r = self.client.post(MANAGE, {"name": "T1", "subject": "s", "body": "b"}, format="json")
        self.assertEqual(r.status_code, 400)        # name already used
        r = self.client.patch(f"{MANAGE}{self.template.id}/", {"kind": "nope"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.patch(f"{MANAGE}99999/", {"subject": "x"}, format="json").status_code, 404)

    def test_subject_is_one_line(self):
        r = self.client.post(MANAGE, {"name": "Line", "subject": "a\nb", "body": "b"}, format="json")
        self.assertNotIn("\n", r.data["subject"])

    def test_needs_a_role(self):
        outsider = User.objects.create_user("nobody", "n@x.com", "pw")
        c = APIClient()
        c.force_authenticate(outsider)
        self.assertEqual(c.get(MANAGE).status_code, 403)
        self.assertEqual(c.get(HISTORY).status_code, 403)


class HistoryTests(OutreachBase):
    def test_lists_newest_first_with_filters(self):
        self.send()
        self.send(confirm=True, subject="Second")
        EmailLog.objects.create(company=self.company, vessel=self.vessel, to_email="ops@acme.com", subject="Broken",
                                body="b", status="failed", error="refused")
        data = self.client.get(HISTORY).data
        self.assertEqual(data["count"], 3)
        self.assertEqual({"to", "body", "company", "vessel", "sent_by", "status"} <= set(data["results"][0]), True)
        self.assertEqual(self.client.get(HISTORY, {"status": "failed"}).data["count"], 1)
        self.assertEqual(self.client.get(HISTORY, {"q": "tester"}).data["count"], 3)
        self.assertEqual(self.client.get(HISTORY, {"q": "zzz"}).data["count"], 0)

    def test_paging(self):
        for i in range(5):
            EmailLog.objects.create(company=self.company, to_email="a@b.com", subject=f"s{i}", body="b", status="test")
        data = self.client.get(HISTORY, {"page_size": 2, "page": 9}).data
        self.assertEqual((data["pages"], data["page"], len(data["results"])), (3, 3, 1))
        self.assertEqual(self.client.get(HISTORY, {"page": "x"}).status_code, 400)


class CheckMailCommandTests(TestCase):
    def run_cmd(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("check_mail", *args, stdout=out)
        return out.getvalue()

    @override_settings(EMAIL_HOST="")
    def test_test_mode_says_so(self):
        self.assertIn("Test mode", self.run_cmd())

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_PORT=587, EMAIL_HOST_USER="u@example.com",
                       EMAIL_HOST_PASSWORD="secret-pw", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_live_settings_are_shown_without_the_password_and_test_mail_is_sent(self):
        out = self.run_cmd("--to", "me@example.com")
        self.assertIn("smtp.example.com:587", out)
        self.assertIn("password: set", out)
        self.assertNotIn("secret-pw", out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["me@example.com"])

    def test_hint_for_a_refused_password(self):
        import smtplib

        from apps.outreach.management.commands.check_mail import hint
        self.assertIn("app password", hint(smtplib.SMTPAuthenticationError(535, b"bad")))


class SafeTestRecipientTests(OutreachBase):
    @override_settings(OUTREACH_TEST_RECIPIENT="dev@gmail.com", OUTREACH_BCC="boss@splendour.com")
    def test_mail_goes_to_the_test_address_only(self):
        r = self.send()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual((msg.to, msg.bcc), (["dev@gmail.com"], []))
        self.assertTrue(msg.subject.startswith("[TEST for ops@acme.com] "))
        log = EmailLog.objects.get()
        self.assertEqual(log.to_email, "dev@gmail.com")
        self.assertEqual(log.company, self.company)

    @override_settings(OUTREACH_TEST_RECIPIENT="dev@gmail.com")
    def test_dialog_is_told_about_the_redirect(self):
        self.assertEqual(self.client.get(TEMPLATES).data["redirect_to"], "dev@gmail.com")
        r = self.client.post(PREVIEW, {"relationship_id": self.rel.id, "template_id": self.template.id}, format="json")
        self.assertEqual(r.data["redirect_to"], "dev@gmail.com")

    @override_settings(OUTREACH_TEST_RECIPIENT="")
    def test_off_by_default(self):
        self.send()
        self.assertEqual(mail.outbox[0].to, ["ops@acme.com"])
