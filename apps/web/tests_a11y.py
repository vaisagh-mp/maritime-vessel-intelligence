"""
apps/web/tests_a11y.py
Automated accessibility tests using standard library html.parser.
Validates structural HTML semantics, landmarks, headings, labeling, and ARIA properties.
"""

from html.parser import HTMLParser
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.opportunities.models import Opportunity
from apps.ports.models import Port
from apps.vessels.models import Vessel

User = get_user_model()


class PageAccessibilityAuditParser(HTMLParser):
    """Parses an HTML document and collects semantic elements for a11y auditing."""

    def __init__(self):
        super().__init__()
        self.html_attrs = {}
        self.ids = []
        self.headings = []  # list of (level, text)
        self.landmarks = []  # list of tag names: header, nav, main
        self.labels = {}  # for_id -> text
        self.form_controls = []  # list of dicts: tag, id, type, aria_label, aria_labelledby
        self.buttons = []  # list of dicts: text, aria_label
        self.dialogs = []  # list of dicts: attrs
        self.links = []  # list of dicts: text, href
        self.aria_live_elements = []  # list of dicts: id, class, aria_live

        self._current_tag = None
        self._current_tag_attrs = {}
        self._text_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._current_tag = tag
        self._current_tag_attrs = attrs_dict
        self._text_buffer = []

        if tag == "html":
            self.html_attrs = attrs_dict

        elem_id = attrs_dict.get("id")
        if elem_id:
            self.ids.append(elem_id)

        if tag in ("header", "nav", "main"):
            self.landmarks.append(tag)

        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            level = int(tag[1])
            self.headings.append((level, ""))

        if tag in ("input", "select", "textarea"):
            ctrl_type = attrs_dict.get("type", "").lower()
            if ctrl_type != "hidden":
                self.form_controls.append({
                    "tag": tag,
                    "id": elem_id,
                    "type": ctrl_type,
                    "aria-label": attrs_dict.get("aria-label"),
                    "aria-labelledby": attrs_dict.get("aria-labelledby"),
                })

        if tag == "dialog":
            self.dialogs.append(attrs_dict)

        if "aria-live" in attrs_dict:
            self.aria_live_elements.append({
                "id": elem_id,
                "class": attrs_dict.get("class", ""),
                "aria-live": attrs_dict["aria-live"],
            })

    def handle_data(self, data):
        self._text_buffer.append(data)

    def handle_endtag(self, tag):
        text = "".join(self._text_buffer).strip()

        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            if self.headings:
                level = self.headings[-1][0]
                self.headings[-1] = (level, text)

        if tag == "label":
            for_id = self._current_tag_attrs.get("for")
            if for_id:
                self.labels[for_id] = text

        if tag == "button":
            self.buttons.append({
                "text": text,
                "aria-label": self._current_tag_attrs.get("aria-label"),
            })

        if tag == "a":
            self.links.append({
                "text": text,
                "href": self._current_tag_attrs.get("href", ""),
            })

        self._current_tag = None
        self._current_tag_attrs = {}
        self._text_buffer = []


class TestWebAccessibilityAudit(TestCase):
    """Audit server-rendered HTML of all main pages for WCAG compliance."""

    def setUp(self):
        self.client = Client()

        # Create groups
        self.admin_group, _ = Group.objects.get_or_create(name=settings.ROLE_ADMIN)
        self.bd_group, _ = Group.objects.get_or_create(name=settings.ROLE_BD_MANAGER)

        # Create admin user
        self.user = User.objects.create_user(
            username="a11y_admin",
            password="testpassword123",
            email="admin@example.com",
        )
        self.user.groups.add(self.admin_group)

        # Create test master data for vessel & lead pages
        self.port = Port.objects.create(
            name="Singapore",
            un_locode="SGSIN",
            latitude=1.29,
            longitude=103.85,
            anchorage_latitude=1.25,
            anchorage_longitude=103.80,
            geofence_radius_km=25.0,
        )
        self.vessel = Vessel.objects.create(
            imo=9998881,
            mmsi=563000001,
            name="PACIFIC GLORY",
            vessel_type="Crude Oil Tanker",
            dwt=105000,
            flag="Singapore",
        )
        self.opportunity = Opportunity.objects.create(
            vessel=self.vessel,
            port=self.port,
            stage="detected",
            score=85,
            zone="24h",
            is_inbound=True,
            lead_reason="High value tanker approaching within 24h",
        )

    def _audit_html(self, html: str, page_name: str):
        parser = PageAccessibilityAuditParser()
        parser.feed(html)

        # 1. <html lang> present
        self.assertIn(
            "lang",
            parser.html_attrs,
            f"[{page_name}] <html lang> attribute is missing",
        )
        self.assertTrue(
            len(parser.html_attrs["lang"].strip()) > 0,
            f"[{page_name}] <html lang> attribute must not be empty",
        )

        # 2. Exactly one <h1> on each page
        h1_list = [h for h in parser.headings if h[0] == 1]
        self.assertEqual(
            len(h1_list),
            1,
            f"[{page_name}] Expected exactly one <h1>, found {len(h1_list)}: {h1_list}",
        )

        # 3. Heading levels never skip (e.g. h1 -> h2 -> h3, no h1 -> h3)
        current_level = 0
        for level, text in parser.headings:
            if current_level == 0:
                self.assertEqual(level, 1, f"[{page_name}] First heading must be <h1>, got <h{level}>")
            else:
                self.assertLessEqual(
                    level,
                    current_level + 1,
                    f"[{page_name}] Heading skipped from <h{current_level}> to <h{level}>: '{text}'",
                )
            current_level = level

        # 4. Landmarks present (header or nav, and exactly one main)
        has_header_or_nav = "header" in parser.landmarks or "nav" in parser.landmarks
        self.assertTrue(
            has_header_or_nav,
            f"[{page_name}] Must contain <header> or <nav> landmark, found: {parser.landmarks}",
        )
        main_count = parser.landmarks.count("main")
        self.assertEqual(
            main_count,
            1,
            f"[{page_name}] Expected exactly one <main> landmark, found {main_count}",
        )

        # 5. Skip link target #main exists
        self.assertIn("main", parser.ids, f"[{page_name}] Skip link target id='main' must exist")

        # 6. All id values are unique
        duplicates = [i for i in parser.ids if parser.ids.count(i) > 1]
        self.assertEqual(
            len(duplicates),
            0,
            f"[{page_name}] Duplicate id values found: {set(duplicates)}",
        )

        # 7. Every form control has a label (for + id, or aria-label, or aria-labelledby)
        for ctrl in parser.form_controls:
            ctrl_id = ctrl["id"]
            has_label_for = ctrl_id and ctrl_id in parser.labels
            has_aria_label = bool(ctrl["aria-label"])
            has_aria_labelledby = bool(ctrl["aria-labelledby"])
            has_accessible_name = has_label_for or has_aria_label or has_aria_labelledby
            self.assertTrue(
                has_accessible_name,
                f"[{page_name}] Form control <{ctrl['tag']} id='{ctrl_id}' type='{ctrl['type']}'> has no accessible label",
            )

        # 8. Every <button> has text or an aria-label
        for btn in parser.buttons:
            has_btn_text = bool(btn["text"])
            has_aria_label = bool(btn["aria-label"])
            self.assertTrue(
                has_btn_text or has_aria_label,
                f"[{page_name}] Button has no text or aria-label: {btn}",
            )

        # 9. The <dialog> has aria-labelledby
        for dlg in parser.dialogs:
            self.assertIn(
                "aria-labelledby",
                dlg,
                f"[{page_name}] <dialog> element must have aria-labelledby",
            )

        # 10. No link text such as "click here"
        for link in parser.links:
            clean_text = link["text"].strip().lower()
            self.assertNotIn("click here", clean_text, f"[{page_name}] Found link with text '{link['text']}'")

        # 11. Toast and status regions have aria-live
        self.assertTrue(
            len(parser.aria_live_elements) > 0,
            f"[{page_name}] Page must include at least one aria-live region for notifications/status",
        )

    def test_accessibility_login_page(self):
        """Audit rendered HTML for /login/ page."""
        res = self.client.get("/login/")
        self.assertEqual(res.status_code, 200)
        self._audit_html(res.content.decode("utf-8"), "Login Page")

    def test_accessibility_no_access_page(self):
        """Audit rendered HTML for no-access response (403 for authenticated user with no role)."""
        user_no_role = User.objects.create_user(username="no_role_user", password="testpassword123")
        self.client.login(username="no_role_user", password="testpassword123")
        res = self.client.get("/")
        self.assertEqual(res.status_code, 403)
        self._audit_html(res.content.decode("utf-8"), "No Access Page")
        self.client.logout()

    def test_accessibility_board_page(self):
        """Audit rendered HTML for lead board page (/)."""
        self.client.login(username="a11y_admin", password="testpassword123")
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self._audit_html(res.content.decode("utf-8"), "Lead Board Page")
        self.client.logout()

    def test_accessibility_vessel_page(self):
        """Audit rendered HTML for vessel detail page (/vessels/<id>/)."""
        self.client.login(username="a11y_admin", password="testpassword123")
        res = self.client.get(f"/vessels/{self.vessel.id}/")
        self.assertEqual(res.status_code, 200)
        self._audit_html(res.content.decode("utf-8"), "Vessel Page")
        self.client.logout()

    def test_accessibility_lead_page(self):
        """Audit rendered HTML for lead detail page (/leads/<id>/)."""
        self.client.login(username="a11y_admin", password="testpassword123")
        res = self.client.get(f"/leads/{self.opportunity.id}/")
        self.assertEqual(res.status_code, 200)
        self._audit_html(res.content.decode("utf-8"), "Lead Page")
        self.client.logout()
