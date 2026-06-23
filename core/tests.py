from django.conf import settings
from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def test_provider_settings_are_loaded_by_the_active_django_project(self):
        self.assertTrue(hasattr(settings, "YOUTUBE_API_KEY"))
        self.assertGreaterEqual(settings.YOUTUBE_MAX_QUERIES, 1)
        self.assertTrue(hasattr(settings, "GDELT_ENABLED"))
        self.assertGreaterEqual(settings.GDELT_MAX_QUERIES, 1)
        self.assertGreaterEqual(settings.GDELT_MAX_RECORDS, 1)

    def test_brazilian_locale_defaults(self):
        self.assertEqual(settings.LANGUAGE_CODE, "pt-br")
        self.assertEqual(settings.TIME_ZONE, "America/Sao_Paulo")
