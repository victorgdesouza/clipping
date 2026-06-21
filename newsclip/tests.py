
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from newsclip.models import Article, Client
from newsclip.templatetags.source_extras import domain


class DomainFilterTests(TestCase):
    def test_domain_filter_removes_www_prefix(self):
        """domain filter deve extrair o host sem o prefixo www."""
        url = "https://www.exemplo.com/algum"
        self.assertEqual(domain(url), "exemplo.com")


@override_settings(SECURE_SSL_REDIRECT=False)
class PublicRoutesTests(TestCase):
    def test_public_pages_are_available(self):
        for route_name in ("landing", "login", "signup"):
            with self.subTest(route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class ClientAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="owner", password="safe-password-123")
        self.other_user = user_model.objects.create_user(username="other", password="safe-password-123")
        self.client_record = Client.objects.create(name="Cliente Teste", keywords="teste")
        self.client_record.users.add(self.user)

    def test_owner_can_access_client_news(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("client_news", args=[self.client_record.pk]))
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_access_client_news(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("client_news", args=[self.client_record.pk]))
        self.assertEqual(response.status_code, 403)


class ReportGenerationTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.client_record = Client.objects.create(name="Cliente Relatorio", keywords="relatorio")
        Article.objects.create(
            client=self.client_record,
            title="Noticia de teste com acentuacao",
            url="https://example.com/noticia",
            source="Fonte Teste",
            published_at=timezone.now(),
        )

    def test_all_report_formats_are_generated(self):
        with override_settings(MEDIA_ROOT=self.temp_dir.name):
            for output_format in ("csv", "xlsx", "pdf"):
                with self.subTest(output_format=output_format):
                    call_command(
                        "generate_report",
                        client_id=self.client_record.pk,
                        days="all",
                        format=output_format,
                    )
                    generated = list(Path(self.temp_dir.name, "reports").glob(f"*.{output_format}"))
                    self.assertEqual(len(generated), 1)
                    self.assertGreater(generated[0].stat().st_size, 0)

