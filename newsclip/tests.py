
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import Mock, patch

from feedparser import FeedParserDict

from newsclip.management.commands.fetch_news import Command
from newsclip.models import Article, Client, GeneratedReport, Source
from newsclip.templatetags.source_extras import domain
from newsclip.utils import save_article
from newsclip.views import check_task_status


class DomainFilterTests(TestCase):
    def test_domain_filter_removes_www_prefix(self):
        """domain filter deve extrair o host sem o prefixo www."""
        url = "https://www.exemplo.com/algum"
        self.assertEqual(domain(url), "exemplo.com")


class NewsCollectionRecallTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(name="Cliente A", keywords="São Paulo")
        self.client_b = Client.objects.create(name="Cliente B", keywords="São Paulo")

    def test_same_url_can_be_relevant_to_different_clients(self):
        url = "https://example.com/noticia-compartilhada"

        first = save_article(self.client_a, "Notícia", url, None, "Exemplo")
        duplicate = save_article(self.client_a, "Notícia", url, None, "Exemplo")
        second_client = save_article(self.client_b, "Notícia", url, None, "Exemplo")

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertIsNotNone(second_client)
        self.assertEqual(Article.objects.filter(url=url).count(), 2)

    @patch("newsclip.management.commands.fetch_news.feedparser.parse")
    def test_rss_matches_accent_insensitive_keyword_in_summary(self, parse_mock):
        source = Source.objects.create(
            name="Fonte RSS",
            url="https://example.com/feed.xml",
            source_type="RSS",
        )
        parse_mock.return_value = FeedParserDict(
            entries=[
                FeedParserDict(
                    title="Agenda econômica da semana",
                    link="https://example.com/agenda",
                    summary="Evento importante em Sao Paulo.",
                )
            ]
        )

        saved = Command().fetch_single_rss(
            self.client_a, source, ["São Paulo"], timezone.now() - timedelta(days=90)
        )

        self.assertEqual(saved, 1)
        self.assertTrue(Article.objects.filter(client=self.client_a, url="https://example.com/agenda").exists())

    @patch("newsclip.management.commands.fetch_news.feedparser.parse")
    @patch("newsclip.management.commands.fetch_news.requests.get")
    def test_google_rss_uses_one_query_per_keyword(self, get_mock, parse_mock):
        get_mock.return_value = Mock(content=b"", status_code=200)
        get_mock.return_value.raise_for_status.return_value = None
        parse_mock.return_value = FeedParserDict(entries=[])

        Command().fetch_google_rss(
            self.client_a, ["termo principal", "termo secundário"], timezone.now() - timedelta(days=90)
        )

        self.assertEqual(get_mock.call_count, 2)


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

