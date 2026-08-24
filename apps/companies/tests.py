from django.test import TestCase

from .models import Company


class CompanyModelTests(TestCase):
    def test_str_is_name(self):
        c = Company.objects.create(name="Anglo-Eastern", company_type="manager")
        self.assertEqual(str(c), "Anglo-Eastern")
        self.assertEqual(c.priority, "medium")
