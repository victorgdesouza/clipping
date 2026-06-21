
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from newsclip.models import Article, Client, GeneratedReport
from newsclip.templatetags.source_extras import domain
from newsclip.views import check_task_status


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
        self.user = get_user_model().objects.create_user(username="reporter", password="safe-password-123")
        self.client_record = Client.objects.create(name="Cliente Relatorio", keywords="relatorio")
        self.client_record.users.add(self.user)
        Article.objects.create(
            client=self.client_record,
            title="Noticia de teste com acentuacao",
            url="https://example.com/noticia",
            source="Fonte Teste",
            published_at=timezone.now(),
        )

    def test_all_report_formats_are_generated(self):
        signatures = {"csv": b"\xef\xbb\xbf", "xlsx": b"PK", "pdf": b"%PDF"}
        for output_format in ("csv", "xlsx", "pdf"):
            with self.subTest(output_format=output_format):
                call_command(
                    "generate_report",
                    client_id=self.client_record.pk,
                    days="all",
                    format=output_format,
                    created_by_id=self.user.pk,
                )
                report = GeneratedReport.objects.get(client=self.client_record, format=output_format)
                content = bytes(report.content)
                self.assertTrue(content.startswith(signatures[output_format]))
                self.assertEqual(report.size, len(content))
                self.assertEqual(report.created_by, self.user)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReportAuthorizationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="report-owner", password="safe-password-123")
        self.other = user_model.objects.create_user(username="report-other", password="safe-password-123")
        self.owner_client = Client.objects.create(name="Cliente A", keywords="a")
        self.other_client = Client.objects.create(name="Cliente B", keywords="b")
        self.owner_client.users.add(self.owner)
        self.other_client.users.add(self.other)
        self.report = GeneratedReport.objects.create(
            client=self.owner_client,
            created_by=self.owner,
            filename="relatorio.csv",
            format="csv",
            period_label="all",
            content_type="text/csv; charset=utf-8",
            content=b"conteudo seguro",
            size=15,
        )

    def test_owner_can_list_and_download_own_report(self):
        self.client.force_login(self.owner)
        list_response = self.client.get(reverse("client_reports", args=[self.owner_client.pk]))
        download_response = self.client.get(
            reverse("download_report", args=[self.owner_client.pk, self.report.pk])
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.content, b"conteudo seguro")

    def test_other_user_cannot_list_generate_or_download_owner_report(self):
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("client_reports", args=[self.owner_client.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("generate_report_view", args=[self.owner_client.pk]),
                {"days": "all", "out_format": "csv"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("download_report", args=[self.other_client.pk, self.report.pk])
            ).status_code,
            404,
        )

    def test_monthly_report_requires_login_and_client_membership(self):
        route = reverse("reports_app:monthly", args=[self.owner_client.pk, 2026, 6])
        self.assertEqual(self.client.get(route).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(route).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(route).status_code, 200)

    def test_task_status_is_restricted_to_superusers(self):
        request = RequestFactory().get("/task-status/test/")
        request.user = self.owner
        self.assertEqual(check_task_status(request, "test").status_code, 403)

