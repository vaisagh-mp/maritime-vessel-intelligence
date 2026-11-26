from django.test import TestCase


class LatestArrivalsPageTests(TestCase):
    def test_page_needs_a_role_and_renders_for_bd(self):
        from django.contrib.auth.models import Group, User
        from django.conf import settings as dj_settings

        self.assertEqual(self.client.get("/latest/").status_code, 302)
        user = User.objects.create_user("latest_bd", "l@x.com", "pw")
        user.groups.add(Group.objects.get_or_create(name=dj_settings.ROLE_BD_MANAGER)[0])
        self.client.force_login(user)
        resp = self.client.get("/latest/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Latest arrivals")
        self.assertContains(resp, "latest.js")


class AllLeadsPageTests(TestCase):
    def test_all_leads_page_and_sidebar_link(self):
        from django.contrib.auth.models import Group, User
        from django.conf import settings as dj_settings

        user = User.objects.create_user("all_bd", "a@x.com", "pw")
        user.groups.add(Group.objects.get_or_create(name=dj_settings.ROLE_BD_MANAGER)[0])
        self.client.force_login(user)
        resp = self.client.get("/priority/all/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "All leads")
        self.assertContains(resp, 'id="filter-new"')
        self.assertContains(resp, 'href="/priority/all/"')
        self.assertEqual(self.client.get("/priority/week/").status_code, 404)


class EmailPagesTests(TestCase):
    def test_pages_need_a_role_and_show_in_sidebar(self):
        from django.contrib.auth.models import Group, User
        from django.conf import settings as dj_settings

        for path in ("/email-templates/", "/email-log/"):
            self.assertEqual(self.client.get(path).status_code, 302)
        nobody = User.objects.create_user("mail_none", "n@x.com", "pw")
        self.client.force_login(nobody)
        self.assertEqual(self.client.get("/email-log/").status_code, 403)
        for role in (dj_settings.ROLE_BD_MANAGER, dj_settings.ROLE_ADMIN):
            user = User.objects.create_user(f"mail_{role}", f"{role}@x.com", "pw")
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            self.client.force_login(user)
            page = self.client.get("/email-templates/")
            self.assertContains(page, "Email templates")
            self.assertContains(page, "email-templates.js")
            self.assertContains(page, 'href="/email-log/"')
            self.assertContains(self.client.get("/email-log/"), "email-log.js")
            self.assertNotContains(page, "/admin/outreach/")
