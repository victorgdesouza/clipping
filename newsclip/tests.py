
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import Mock, patch

from feedparser import FeedParserDict

from newsclip.management.commands.fetch_news import Command, ensure_essential_news_sources
from newsclip.discovery import (
    build_discovery_queries,
    discover_client_sources,
    fetch_sitemap_endpoint,
    maybe_promote_source,
    parse_sitemap,
    profile_source,
)
from newsclip.models import Article, Client, DiscoveryResult, DiscoveryRun, FetchLog, GeneratedReport, Source, SourceEndpoint
from newsclip.providers import fetch_gdelt, fetch_youtube
from newsclip.signals import update_search_vector
from newsclip.tasks import fetch_news_task
from newsclip.templatetags.source_extras import domain
from newsclip.utils import (
    build_essential_source_queries,
    deduplicate_articles_for_display,
    legacy_keyword_identity_terms,
    record_endpoint_failure,
    save_article,
    validate_article_candidate,
)
from newsclip.views import check_task_status


class DomainFilterTests(TestCase):
    def test_domain_filter_removes_www_prefix(self):
        """domain filter deve extrair o host sem o prefixo www."""
        url = "https://www.exemplo.com/algum"
        self.assertEqual(domain(url), "exemplo.com")


class NewsCollectionRecallTests(TestCase):
    def setUp(self):
        self.client_a = Client.objects.create(name="Cliente A", name_variations="São Paulo")
        self.client_b = Client.objects.create(name="Cliente B", name_variations="São Paulo")

    def test_same_url_can_be_relevant_to_different_clients(self):
        url = "https://example.com/noticia-compartilhada"

        first = save_article(self.client_a, "Notícia sobre São Paulo", url, None, "Exemplo")
        duplicate = save_article(self.client_a, "Notícia sobre São Paulo", url, None, "Exemplo")
        second_client = save_article(self.client_b, "Notícia sobre São Paulo", url, None, "Exemplo")

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertIsNotNone(second_client)
        self.assertEqual(Article.objects.filter(url=url).count(), 2)

    def test_same_story_from_same_source_is_saved_only_once(self):
        first = save_article(
            self.client_a,
            "São Paulo anuncia novo projeto - Jornal Exemplo",
            "https://jornal.example/materia?utm_source=google",
            None,
            "Jornal Exemplo",
        )
        repeated = save_article(
            self.client_a,
            "São Paulo anuncia novo projeto",
            "https://jornal.example/materia?ref=homepage",
            None,
            "Jornal Exemplo",
        )

        self.assertIsNotNone(first)
        self.assertIsNone(repeated)
        self.assertEqual(Article.objects.filter(client=self.client_a).count(), 1)
        self.assertEqual(Article.objects.get(client=self.client_a).url, "https://jornal.example/materia")

    def test_same_title_from_different_sources_is_saved_only_once(self):
        save_article(self.client_a, "Noticia importante de São Paulo", "https://a.example/1", None, "Fonte A")
        save_article(self.client_a, "Noticia importante de São Paulo", "https://b.example/2", None, "Fonte B")

        self.assertEqual(Article.objects.filter(client=self.client_a).count(), 1)

    def test_existing_duplicate_titles_are_hidden_from_display(self):
        Article.objects.create(
            client=self.client_a,
            title="Justiça de Rio Preto determina bloqueio de bens - G1",
            url="https://g1.globo.com/sp/rio-preto/noticia/1",
            source="G1",
            published_at=timezone.now(),
            dedup_key="legacy-g1-1",
        )
        Article.objects.create(
            client=self.client_a,
            title="Justiça de Rio Preto determina bloqueio de bens",
            url="https://g1.globo.com/sp/rio-preto/noticia/1?utm_source=google",
            source="g1.globo.com",
            published_at=timezone.now(),
            dedup_key="legacy-g1-2",
        )

        visible = deduplicate_articles_for_display(
            Article.objects.filter(client=self.client_a).order_by("-published_at", "-id")
        )

        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].url.split("?", 1)[0], "https://g1.globo.com/sp/rio-preto/noticia/1")

    def test_excluded_term_blocks_ambiguous_city(self):
        self.client_a.excluded_keywords = "Rio Preto da Eva"
        self.client_a.save(update_fields=["excluded_keywords"])

        saved = save_article(
            self.client_a,
            "Obras avancam em Rio Preto da Eva",
            "https://example.com/rio-preto-da-eva",
            None,
            "Jornal Exemplo",
        )

        self.assertIsNone(saved)
        self.assertFalse(Article.objects.filter(client=self.client_a).exists())

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

    @patch("newsclip.management.commands.fetch_news.feedparser.parse")
    @patch("newsclip.management.commands.fetch_news.requests.get")
    def test_google_rss_respects_explicit_query_limit(self, get_mock, parse_mock):
        get_mock.return_value = Mock(content=b"", status_code=200)
        get_mock.return_value.raise_for_status.return_value = None
        parse_mock.return_value = FeedParserDict(entries=[])

        Command().fetch_google_rss(
            self.client_a,
            ["q1", "q2", "q3", "q4"],
            timezone.now() - timedelta(days=90),
            max_queries=3,
        )

        self.assertEqual(get_mock.call_count, 3)

    def test_essential_source_queries_include_major_and_regional_portals(self):
        queries = build_essential_source_queries(self.client_a, max_sources=24)
        joined = "\n".join(queries)

        self.assertIn('site:g1.globo.com', joined)
        self.assertIn('site:g1.globo.com/sp/sao-jose-do-rio-preto-aracatuba', joined)
        self.assertIn('site:record.r7.com/record-rio-preto', joined)
        self.assertIn('site:band.uol.com.br', joined)

    def test_legacy_public_keywords_are_used_as_identity_aliases(self):
        client = Client.objects.create(
            name="Fábio Candido",
            keywords=(
                "Prefeito de Rio Preto, Coronel Fábio Candido, "
                "Prefeitura de Rio Preto, rodeio, show"
            ),
        )

        aliases = legacy_keyword_identity_terms(client)
        queries = build_essential_source_queries(client, max_sources=8)
        joined = "\n".join(queries)

        self.assertIn("Prefeito de Rio Preto", aliases)
        self.assertIn("Coronel Fábio Candido", aliases)
        self.assertNotIn("Prefeitura de Rio Preto", aliases)
        self.assertNotIn("rodeio", aliases)
        self.assertNotIn("show", aliases)
        self.assertIn('"Prefeito de Rio Preto" site:g1.globo.com', joined)

    def test_ensure_essential_sources_registers_verified_sources(self):
        ensure_essential_news_sources()

        self.assertTrue(Source.objects.filter(name="G1", is_active=True, status="ACTIVE").exists())
        self.assertTrue(Source.objects.filter(name="Record Rio Preto", is_active=True, status="ACTIVE").exists())
        self.assertTrue(Source.objects.filter(name="Band Paulista", is_active=True, status="ACTIVE").exists())


class SearchVectorSignalTests(TestCase):
    @patch("newsclip.signals.Article.objects.filter")
    @patch("newsclip.signals.connection")
    def test_postgres_uses_search_vector_expression_instead_of_raw_text(self, connection_mock, filter_mock):
        connection_mock.vendor = "postgresql"
        instance = Mock(pk=123, title="Título", summary="Resumo", content="Conteúdo", source="Fonte")

        update_search_vector(Article, instance, created=True)

        filter_mock.assert_called_once_with(pk=123)
        vector = filter_mock.return_value.update.call_args.kwargs["search_vector"]
        self.assertNotIsInstance(vector, str)


class AdvancedValidationTests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(
            name="Sao Jose do Rio Preto",
            name_variations="Rio Preto",
            context_terms="mobilidade urbana",
            excluded_keywords="Rio Preto da Eva",
        )

    def test_title_match_is_accepted_with_high_score(self):
        result = validate_article_candidate(
            self.client_record,
            "Rio Preto anuncia plano de mobilidade urbana",
            "Novo projeto municipal",
            "https://jornal.example/materia",
            "Jornal Local",
        )

        self.assertEqual(result["status"], "ACCEPTED")
        self.assertGreaterEqual(result["score"], 70)

    def test_ambiguous_excluded_location_is_rejected(self):
        result = validate_article_candidate(
            self.client_record,
            "Evento em Rio Preto da Eva",
            "Agenda do Amazonas",
            "https://amazonas.example/evento",
            "Fonte Amazonas",
        )

        self.assertEqual(result["status"], "REJECTED")

    def test_legacy_public_role_keyword_can_accept_mayor_news(self):
        client = Client.objects.create(
            name="Fábio Candido",
            keywords="Prefeito de Rio Preto, Coronel Fábio Candido, Prefeitura de Rio Preto",
            excluded_keywords="Rio Preto da Eva",
        )

        result = validate_article_candidate(
            client,
            "Prefeito de Rio Preto assina ordem de serviço para novas obras",
            "",
            "https://gazetaderiopreto.com.br/noticias/prefeito-assina-ordem-servico",
            "Gazeta de Rio Preto",
            provider="GOOGLE_RSS",
        )

        self.assertEqual(result["status"], "ACCEPTED")
        self.assertGreaterEqual(result["score"], 70)

    def test_prefeitura_context_without_mayor_entity_is_not_accepted(self):
        client = Client.objects.create(
            name="Fábio Candido",
            keywords="Prefeito de Rio Preto, Coronel Fábio Candido, Prefeitura de Rio Preto",
        )

        result = validate_article_candidate(
            client,
            "Prefeitura de Rio Preto vai usar nova técnica para esterilizar mosquitos da dengue",
            "",
            "https://g1.globo.com/sp/sao-jose-do-rio-preto-aracatuba/noticia/prefeitura-mosquitos.ghtml",
            "G1",
            provider="GOOGLE_RSS",
        )

        self.assertNotEqual(result["status"], "ACCEPTED")


class CountryBullsRelevanceTests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(
            name="Rio Preto Country Bulls",
            name_variations="Country Bulls, riopretocountrybulls, @riopretocountrybullsoficial",
            context_terms=(
                "Paulo Emílio, São José do Rio Preto, Rio Preto, rodeio, arena, "
                "evento, touro, peão, ingressos, show, festival, doação solidária"
            ),
            domains="arenacp.com.br/carlinhos-pinheiro",
            instagram="@riopretocountrybullsoficial",
            youtube="@riopretocountrybullsoficial",
        )

    def assert_rejected(self, title):
        result = validate_article_candidate(
            self.client_record,
            title,
            "",
            "https://example.com/noticia",
            "Fonte Teste",
        )
        self.assertEqual(result["status"], "REJECTED", title)
        self.assertLess(result["score"], 40)

    def assert_accepted(self, title, content="", url="https://example.com/noticia", source="Fonte Teste"):
        result = validate_article_candidate(
            self.client_record,
            title,
            content,
            url,
            source,
        )
        self.assertEqual(result["status"], "ACCEPTED", title)
        self.assertGreaterEqual(result["score"], 70)

    def test_rejects_generic_city_and_rodeo_false_positives(self):
        rejected_titles = [
            "Prefeitura apresenta estudo da PGV e anuncia desconto no IPTU 2027 em São José do Rio Preto",
            "Adolescente de 13 anos desaparece em Rio Preto",
            "Netflix anuncia Johnny Massaro e Rodrigo Santoro em nova serie",
            "EXPOVG 2026 reúne atrações musicais, rodeio e cultura em Várzea Grande",
            "Delegado acusado de matar adolescente na saída de rodeio",
            "Jogo do Brasil altera horário de expediente da Prefeitura de Rio Preto",
            "15º Rodeio de Caminhões da Raízen",
            "Paulo Coelho participa de evento cultural",
            "Exportação de gado vivo acelera e coloca Brasil no caminho de um recorde em 2026",
            "RS apresenta plataforma de alerta climático para a produção pecuária",
            "Agroleite 2026 abre inscrições de animais das raças Holandesa e Jersey para julgamentos",
            "Mirassol anuncia parceria estratégica com a Rodobens",
        ]
        for title in rejected_titles:
            with self.subTest(title=title):
                self.assert_rejected(title)

    def test_rejects_generic_non_official_youtube_results(self):
        rejected_samples = [
            ("■ NÃO é truque■", "https://www.youtube.com/watch?v=7h6U0V3mCZg", "YouTube - André Moraes Mestre Queijeiro"),
            ("mozzarella AO VIVO ■", "https://www.youtube.com/watch?v=QVvnE9eCkxk", "YouTube - André Moraes Mestre Queijeiro"),
        ]
        for title, url, source in rejected_samples:
            with self.subTest(title=title):
                result = validate_article_candidate(self.client_record, title, "", url, source, provider="YOUTUBE")
                self.assertEqual(result["status"], "REJECTED", title)
                self.assertLess(result["score"], 40)

    def test_accepts_country_bulls_related_results(self):
        accepted_titles = [
            "Cassio Dias Barbosa X Touro Café Cia Guto Paglione: Campeão Rio Preto Country Bulls 2022",
            "Paulo Emílio conta um pouco do começo do Country Bulls",
            "Parceria entre Country Bulls e HB chega a quase 10 anos com nova doação solidária",
            "REGIÃO: RODEIO E PROMOÇÃO! Consumidores de Açúcar Guarani podem concorrer a ingressos para o Country Bulls 2026",
        ]
        for title in accepted_titles:
            with self.subTest(title=title):
                self.assert_accepted(title)

    def test_official_profile_accepts_short_official_post(self):
        self.assert_accepted(
            "ENTRADA SOLIDÁRIA",
            url="https://www.youtube.com/@riopretocountrybullsoficial/videos",
            source="YouTube - riopretocountrybullsoficial",
        )

    def test_non_official_youtube_requires_strong_identity(self):
        self.assert_accepted(
            "Rio Preto Country Bulls chega à 28ª edição com novidades e grandes atrações",
            url="https://www.youtube.com/watch?v=e97sXMcaFz8",
            source="YouTube - TH+ SBT Interior",
        )

    def test_context_only_is_not_saved_as_final_article(self):
        saved = save_article(
            self.client_record,
            "Prefeitura anuncia nova obra em São José do Rio Preto",
            "https://example.com/prefeitura",
            None,
            "Portal Local",
            "Texto fala apenas da cidade e nao do evento.",
            provider="GOOGLE_RSS",
            query='"São José do Rio Preto"',
        )

        self.assertIsNone(saved)
        self.assertFalse(Article.objects.filter(client=self.client_record).exists())

    def test_identity_only_in_snippet_does_not_become_accepted_article(self):
        result = validate_article_candidate(
            self.client_record,
            "52º Expoleite destaca genética leiteira e programação para produtores em Arapoti",
            "Busca relacionada a Rio Preto Country Bulls, rodeio e evento.",
            "https://canaldocriador.com.br/expoleite-arapoti",
            "Canal do Criador",
            provider="GOOGLE_RSS",
        )

        self.assertNotEqual(result["status"], "ACCEPTED")
        self.assertLess(result["score"], 70)


class AdditionalProvidersTests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(name="Cliente Regional", keywords="mobilidade")
        self.since = timezone.now() - timedelta(days=30)

    @override_settings(YOUTUBE_API_KEY="youtube-test", YOUTUBE_MAX_QUERIES=1)
    @patch("newsclip.providers.requests.get")
    def test_youtube_search_saves_video_with_provider(self, get_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [{
                "id": {"videoId": "video123"},
                "snippet": {
                    "title": "Cliente Regional debate mobilidade",
                    "description": "Entrevista local",
                    "channelTitle": "TV Local",
                    "publishedAt": "2026-06-23T10:00:00Z",
                },
            }]
        }
        get_mock.return_value = response

        saved = fetch_youtube(self.client_record, ["mobilidade"], self.since)

        self.assertEqual(saved, 1)
        article = Article.objects.get(client=self.client_record)
        self.assertEqual(article.provider, "YOUTUBE")
        self.assertEqual(article.validation_status, "ACCEPTED")
        self.assertEqual(DiscoveryRun.objects.get(provider="YOUTUBE").status, "SUCCESS")

    @override_settings(YOUTUBE_API_KEY="youtube-test", YOUTUBE_MAX_QUERIES=1)
    @patch("newsclip.providers.feedparser.parse")
    @patch("newsclip.providers.requests.get")
    def test_channel_feed_does_not_disable_broad_youtube_search(self, get_mock, parse_mock):
        self.client_record.youtube = "https://youtube.com/channel/UC1234567890123456789012"
        self.client_record.save(update_fields=["youtube"])
        feed_response = Mock(content=b"")
        feed_response.raise_for_status.return_value = None
        search_response = Mock()
        search_response.raise_for_status.return_value = None
        search_response.json.return_value = {
            "items": [{
                "id": {"videoId": "broad456"},
                "snippet": {
                    "title": "Cliente Regional em reportagem ampla",
                    "description": "mobilidade",
                    "channelTitle": "Canal Nao Cadastrado",
                    "publishedAt": "2026-06-23T10:00:00Z",
                },
            }]
        }
        get_mock.side_effect = [feed_response, search_response]
        parse_mock.return_value = FeedParserDict(entries=[])

        saved = fetch_youtube(self.client_record, ["mobilidade"], self.since)

        self.assertEqual(saved, 1)
        self.assertEqual(get_mock.call_count, 2)
        self.assertIn("search", get_mock.call_args_list[1].args[0])

    @override_settings(GDELT_MAX_QUERIES=1, GDELT_MAX_RECORDS=10)
    @patch("newsclip.providers.requests.get")
    def test_gdelt_saves_article_and_run_metrics(self, get_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "articles": [{
                "title": "Cliente Regional apresenta plano de mobilidade",
                "url": "https://jornal.example/plano",
                "domain": "jornal.example",
                "seendate": "20260623T120000Z",
            }]
        }
        get_mock.return_value = response

        saved = fetch_gdelt(self.client_record, ["mobilidade"], self.since)

        self.assertEqual(saved, 1)
        self.assertEqual(Article.objects.get(client=self.client_record).provider, "GDELT")
        run = DiscoveryRun.objects.get(provider="GDELT")
        self.assertEqual(run.results_count, 1)
        self.assertEqual(run.articles_count, 1)

    @override_settings(GDELT_MAX_QUERIES=1, GDELT_RATE_LIMIT_SLEEP_SECONDS=0)
    @patch("newsclip.providers.requests.get")
    def test_gdelt_rate_limit_is_handled_as_partial_without_raising(self, get_mock):
        response = Mock(status_code=429, headers={})
        response.raise_for_status.side_effect = AssertionError("raise_for_status should not run for repeated 429")
        get_mock.return_value = response
        log_mock = Mock()

        saved = fetch_gdelt(self.client_record, ["mobilidade"], self.since, log=log_mock)

        self.assertEqual(saved, 0)
        run = DiscoveryRun.objects.get(provider="GDELT")
        self.assertEqual(run.status, "PARTIAL")
        self.assertIn("limitou temporariamente", run.error_message)
        log_mock.assert_called_once()
        self.assertIn("limitou temporariamente", log_mock.call_args.args[0])


class AutomaticDiscoveryTests(TestCase):
    def setUp(self):
        self.client_record = Client.objects.create(
            name="Joao da Silva",
            name_variations="Joao Silva",
            context_terms="mobilidade urbana",
        )

    def test_query_campaign_includes_client_and_keywords_without_duplicates(self):
        queries = build_discovery_queries(
            self.client_record,
            ["Joao Silva", "mobilidade urbana"],
            max_queries=20,
        )

        self.assertIn('"Joao da Silva"', queries)
        self.assertIn('"Joao Silva" noticias', queries)
        self.assertEqual(len(queries), len(set(queries)))

    @override_settings(
        BRAVE_SEARCH_API_KEY="test-key",
        BRAVE_SEARCH_MAX_QUERIES=2,
        BRAVE_SEARCH_RESULTS_PER_QUERY=20,
        DISCOVERY_PROFILE_NEW_SOURCES=5,
    )
    @patch("newsclip.discovery.profile_source", return_value=0)
    @patch("newsclip.discovery.requests.get")
    def test_brave_registers_article_source_and_discovery_evidence(self, get_mock, _profile_mock):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Joao da Silva anuncia plano de mobilidade",
                        "url": "https://jornal-local.example/noticia?utm_source=teste",
                        "description": "Entrevista sobre mobilidade urbana.",
                        "page_age": "2026-06-22T10:00:00Z",
                    }
                ]
            }
        }
        get_mock.return_value = response

        stats = discover_client_sources(
            self.client_record,
            ["Joao Silva", "mobilidade urbana"],
        )

        self.assertEqual(stats["new_sources"], 1)
        self.assertEqual(stats["articles"], 1)
        source = Source.objects.get(domain="jornal-local.example")
        self.assertTrue(source.discovered_automatically)
        self.assertEqual(source.status, "CANDIDATE")
        self.assertTrue(DiscoveryResult.objects.filter(client=self.client_record, is_relevant=True).exists())
        article = Article.objects.get(client=self.client_record)
        self.assertNotIn("utm_source", article.url)
        run = DiscoveryRun.objects.get(client=self.client_record, provider="BRAVE")
        self.assertEqual(run.status, "SUCCESS")
        requests_after_first_run = get_mock.call_count

        second_stats = discover_client_sources(
            self.client_record,
            ["Joao Silva", "mobilidade urbana"],
        )

        self.assertEqual(second_stats["skipped"], 1)
        self.assertEqual(get_mock.call_count, requests_after_first_run)

    @override_settings(
        BRAVE_SEARCH_API_KEY="test-key",
        BRAVE_SEARCH_MAX_QUERIES=1,
        DISCOVERY_PROFILE_NEW_SOURCES=0,
    )
    @patch("newsclip.discovery.requests.get")
    def test_brave_rejects_result_with_excluded_term(self, get_mock):
        self.client_record.excluded_keywords = "Rio Preto da Eva"
        self.client_record.save(update_fields=["excluded_keywords"])
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Evento realizado em Rio Preto da Eva",
                        "url": "https://amazonas.example/evento",
                        "description": "Agenda municipal",
                    }
                ]
            }
        }
        get_mock.return_value = response

        stats = discover_client_sources(self.client_record, ["Rio Preto"])

        self.assertEqual(stats["relevant"], 0)
        self.assertEqual(stats["articles"], 0)
        self.assertFalse(Article.objects.filter(client=self.client_record).exists())
        result = DiscoveryResult.objects.get(client=self.client_record)
        self.assertFalse(result.is_relevant)

    @patch("newsclip.discovery.is_public_http_url", return_value=True)
    @patch("newsclip.discovery.requests.get")
    def test_source_profiler_detects_rss_and_sitemap(self, get_mock, _public_mock):
        source = Source.objects.create(
            name="Jornal Automatico",
            domain="jornal.example",
            url="https://jornal.example/",
            source_type="DISCOVERED",
            status="CANDIDATE",
            is_active=False,
        )
        homepage = Mock(
            url="https://jornal.example/",
            text='<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>',
        )
        homepage.raise_for_status.return_value = None
        robots = Mock(ok=True, text="Sitemap: https://jornal.example/news-sitemap.xml")
        get_mock.side_effect = [homepage, robots]

        created = profile_source(source)

        self.assertEqual(created, 2)
        self.assertEqual(Source.objects.get(pk=source.pk).status, "VERIFIED")
        self.assertSetEqual(
            set(SourceEndpoint.objects.filter(source=source).values_list("endpoint_type", flat=True)),
            {"RSS", "NEWS_SITEMAP"},
        )

    @override_settings(
        DISCOVERY_AUTO_ACTIVATE_SOURCES=True,
        DISCOVERY_AUTO_ACTIVATE_MIN_RELEVANT_RESULTS=2,
        DISCOVERY_AUTO_ACTIVATE_MIN_CLIENTS=1,
        DISCOVERY_AUTO_ACTIVATE_MIN_CONFIDENCE=50,
    )
    def test_reusable_discovered_source_is_promoted_to_global_active_source(self):
        source = Source.objects.create(
            name="Jornal Reutilizavel",
            domain="jornal-reutilizavel.example",
            url="https://jornal-reutilizavel.example/",
            source_type="DISCOVERED",
            discovered_automatically=True,
            status="VERIFIED",
            is_active=False,
            confidence_score=60,
        )
        SourceEndpoint.objects.create(
            source=source,
            endpoint_type="RSS",
            url="https://jornal-reutilizavel.example/feed.xml",
            is_active=True,
        )
        for index in range(2):
            DiscoveryResult.objects.create(
                client=self.client_record,
                source=source,
                provider="BRAVE",
                query='"Joao da Silva"',
                title=f"Joao da Silva noticia relevante {index}",
                url=f"https://jornal-reutilizavel.example/noticia-{index}",
                relevance_score=100,
                is_relevant=True,
            )

        promoted = maybe_promote_source(source)

        source.refresh_from_db()
        self.assertTrue(promoted)
        self.assertTrue(source.is_active)
        self.assertEqual(source.status, "ACTIVE")

    @override_settings(
        DISCOVERY_AUTO_ACTIVATE_SOURCES=True,
        DISCOVERY_AUTO_ACTIVATE_MIN_RELEVANT_RESULTS=2,
        DISCOVERY_AUTO_ACTIVATE_MIN_CLIENTS=1,
        DISCOVERY_AUTO_ACTIVATE_MIN_CONFIDENCE=50,
    )
    def test_discovered_source_without_enough_evidence_stays_inactive(self):
        source = Source.objects.create(
            name="Jornal Candidato",
            domain="jornal-candidato.example",
            url="https://jornal-candidato.example/",
            source_type="DISCOVERED",
            discovered_automatically=True,
            status="VERIFIED",
            is_active=False,
            confidence_score=60,
        )
        SourceEndpoint.objects.create(
            source=source,
            endpoint_type="RSS",
            url="https://jornal-candidato.example/feed.xml",
            is_active=True,
        )
        DiscoveryResult.objects.create(
            client=self.client_record,
            source=source,
            provider="BRAVE",
            query='"Joao da Silva"',
            title="Joao da Silva noticia relevante",
            url="https://jornal-candidato.example/noticia",
            relevance_score=100,
            is_relevant=True,
        )

        promoted = maybe_promote_source(source)

        source.refresh_from_db()
        self.assertFalse(promoted)
        self.assertFalse(source.is_active)
        self.assertEqual(source.status, "VERIFIED")

    def test_news_sitemap_parser_extracts_title_and_date(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
                xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
          <url><loc>https://jornal.example/materia</loc><news:news>
            <news:publication_date>2026-06-22T10:00:00Z</news:publication_date>
            <news:title>Joao Silva participa de evento</news:title>
          </news:news></url>
        </urlset>"""

        children, articles = parse_sitemap(xml)

        self.assertEqual(children, [])
        self.assertEqual(articles[0]["title"], "Joao Silva participa de evento")
        self.assertEqual(articles[0]["publication_date"], "2026-06-22T10:00:00Z")

    @override_settings(DISCOVERY_MIN_RELEVANCE_SCORE=35, SITEMAP_MAX_ARTICLES=10)
    @patch("newsclip.discovery.is_public_http_url", return_value=True)
    @patch("newsclip.discovery.requests.get")
    def test_news_sitemap_saves_relevant_article(self, get_mock, _public_mock):
        source = Source.objects.create(
            name="Jornal de Teste",
            domain="jornal.example",
            url="https://jornal.example/",
            source_type="NEWS_SITEMAP",
        )
        endpoint = SourceEndpoint.objects.create(
            source=source,
            endpoint_type="NEWS_SITEMAP",
            url="https://jornal.example/news-sitemap.xml",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
          xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url>
          <loc>https://jornal.example/materia</loc><news:news>
          <news:publication_date>2026-06-22T10:00:00Z</news:publication_date>
          <news:title>Joao Silva apresenta novo projeto</news:title>
          </news:news></url></urlset>"""
        get_mock.return_value = response

        saved = fetch_sitemap_endpoint(
            Command(),
            self.client_record,
            endpoint,
            ["Joao Silva"],
            timezone.now() - timedelta(days=90),
        )

        self.assertEqual(saved, 1)
        self.assertTrue(Article.objects.filter(client=self.client_record, source="Jornal de Teste").exists())


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

    def test_dashboard_hides_internal_coverage_metrics(self):
        save_article(
            self.client_record,
            "Cliente Teste aparece em noticia local",
            "https://jornal.example/noticia",
            timezone.now().isoformat(),
            "Jornal Local",
            "Conteudo sobre o cliente teste",
            provider="GDELT",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cobertura")
        self.assertNotContains(response, "Provedores ativos")
        self.assertNotContains(response, "GDELT")

    @patch("newsclip.views.revalidate_accepted_articles_for_client")
    def test_dashboard_does_not_run_expensive_revalidation(self, revalidate_mock):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        revalidate_mock.assert_not_called()

    def test_client_news_hides_source_and_quality_columns(self):
        save_article(
            self.client_record,
            "Cliente Teste aparece em noticia local",
            "https://jornal.example/noticia",
            timezone.now().isoformat(),
            "Jornal Local",
            "Conteudo sobre o cliente teste",
            provider="GDELT",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("client_news", args=[self.client_record.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<th>Fonte</th>", html=True)
        self.assertNotContains(response, "<th>Qualidade</th>", html=True)

    def test_client_news_review_queue_is_visible(self):
        Article.objects.create(
            client=self.client_record,
            title="Cliente Teste em noticia ambigua",
            url="https://jornal.example/review",
            source="Jornal Local",
            published_at=timezone.now(),
            validation_status="REVIEW",
            relevance_score=55,
            validation_reason="Identidade fraca + contexto",
            dedup_key="review-visible",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("client_news", args=[self.client_record.pk]) + "?status=review")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revisar (1)")
        self.assertContains(response, "Cliente Teste em noticia ambigua")
        self.assertContains(response, "Identidade fraca + contexto")

    def test_monitored_sources_requires_login(self):
        response = self.client.get(reverse("monitored_sources"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_logged_user_can_consult_active_and_verified_sources(self):
        active_source = Source.objects.create(
            name="Jornal Ativo",
            domain="jornalativo.example",
            url="https://jornalativo.example/",
            source_type="DISCOVERED",
            status="ACTIVE",
            is_active=True,
            discovered_automatically=True,
            discovery_count=3,
        )
        SourceEndpoint.objects.create(
            source=active_source,
            endpoint_type="RSS",
            url="https://jornalativo.example/feed.xml",
            is_active=True,
        )
        Source.objects.create(
            name="Jornal Verificado",
            domain="jornalverificado.example",
            url="https://jornalverificado.example/",
            source_type="DISCOVERED",
            status="VERIFIED",
            is_active=False,
            discovered_automatically=True,
            discovery_count=1,
        )
        Source.objects.create(
            name="Jornal Candidato",
            domain="jornalcandidato.example",
            url="https://jornalcandidato.example/",
            source_type="DISCOVERED",
            status="CANDIDATE",
            is_active=False,
            discovered_automatically=True,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("monitored_sources"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fontes monitoradas")
        self.assertContains(response, "Jornal Ativo")
        self.assertContains(response, "Ativa nas buscas")
        self.assertContains(response, "https://jornalativo.example/")
        self.assertContains(response, "Jornal Verificado")
        self.assertContains(response, "Verificada")
        self.assertContains(response, "<th>Site</th>", html=True)
        self.assertContains(response, "<th>Link</th>", html=True)
        self.assertNotContains(response, "RSS/Atom")
        self.assertNotContains(response, "Descobertas")
        self.assertNotContains(response, "Última descoberta")
        self.assertNotContains(response, "https://jornalativo.example/feed.xml")
        self.assertNotContains(response, "Jornal Candidato")

    def test_logged_user_can_filter_degraded_sources(self):
        degraded = Source.objects.create(
            name="Jornal Degradado",
            domain="degradado.example",
            url="https://degradado.example/",
            source_type="DISCOVERED",
            status="DEGRADED",
            is_active=True,
        )
        SourceEndpoint.objects.create(
            source=degraded,
            endpoint_type="NEWS_SITEMAP",
            url="https://degradado.example/news-sitemap.xml",
            is_active=True,
            consecutive_errors=4,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("monitored_sources") + "?status=degraded")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jornal Degradado")
        self.assertContains(response, "Com falhas")

    @override_settings(SOURCE_ENDPOINT_DEGRADED_AFTER_ERRORS=1, SOURCE_ENDPOINT_DISABLE_AFTER_ERRORS=0)
    def test_endpoint_failure_logs_alert_and_marks_source_degraded(self):
        source = Source.objects.create(
            name="Jornal Instavel",
            domain="instavel.example",
            url="https://instavel.example/",
            source_type="DISCOVERED",
            status="ACTIVE",
            is_active=True,
        )
        endpoint = SourceEndpoint.objects.create(
            source=source,
            endpoint_type="RSS",
            url="https://instavel.example/feed.xml",
            is_active=True,
        )

        record_endpoint_failure(endpoint, RuntimeError("timeout"), client=self.client_record)

        endpoint.refresh_from_db()
        source.refresh_from_db()
        self.assertTrue(endpoint.is_active)
        self.assertEqual(endpoint.consecutive_errors, 1)
        self.assertEqual(source.status, "DEGRADED")
        self.assertTrue(FetchLog.objects.filter(source=source, level="WARNING").exists())

    @patch("newsclip.views.async_task", return_value="task-123")
    def test_owner_starts_fetch_in_background(self, async_task_mock):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("fetch_news", args=[self.client_record.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        self.assertIn("task-123", response.json()["status_url"])
        async_task_mock.assert_called_once_with(
            "newsclip.tasks.fetch_news_task",
            self.client_record.pk,
            response.json()["task_id"] if response.json()["task_id"].isdigit() else 1,
            task_name=f"fetch-news-client-{self.client_record.pk}",
        )

    @patch("newsclip.tasks.call_command")
    def test_fetch_news_task_uses_quick_mode_for_interactive_search(self, call_command_mock):
        fetch_news_task(self.client_record.pk)

        call_command_mock.assert_called_once_with(
            "fetch_news",
            "--client-id",
            str(self.client_record.pk),
            "--quick",
        )


class ReportGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reporter", password="safe-password-123")
        self.client_record = Client.objects.create(name="Cliente Relatorio", keywords="relatorio")
        self.client_record.users.add(self.user)
        Article.objects.create(
            client=self.client_record,
            title="Cliente Relatorio aparece em noticia de teste com acentuacao",
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

    def test_report_revalidates_stale_accepted_articles(self):
        client = Client.objects.create(
            name="Rio Preto Country Bulls",
            name_variations="Country Bulls, riopretocountrybulls",
            context_terms="Rio Preto, rodeio, gado, pecuaria, ingressos",
        )
        client.users.add(self.user)
        Article.objects.create(
            client=client,
            title="Rio Preto Country Bulls terá nova edição",
            url="https://example.com/country-bulls",
            source="Fonte Teste",
            published_at=timezone.now(),
            validation_status="ACCEPTED",
            relevance_score=100,
            dedup_key="country-bulls-valid",
        )
        stale = Article.objects.create(
            client=client,
            title="Exportação de gado vivo acelera e coloca Brasil no caminho de um recorde em 2026",
            url="https://canaldocriador.com.br/geral/exportacao-de-gado-vivo-recorde-2026",
            source="Canal do Criador",
            published_at=timezone.now(),
            validation_status="ACCEPTED",
            relevance_score=100,
            dedup_key="country-bulls-stale-invalid",
        )

        call_command("generate_report", client_id=client.pk, days="all", format="csv", created_by_id=self.user.pk)

        stale.refresh_from_db()
        report = GeneratedReport.objects.get(client=client, format="csv")
        content = bytes(report.content).decode("utf-8-sig")
        self.assertEqual(stale.validation_status, "REJECTED")
        self.assertIn("Rio Preto Country Bulls terá nova edição", content)
        self.assertNotIn("Exportação de gado vivo", content)


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

