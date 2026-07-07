# newsclip/management/commands/fetch_news.py

import os
import time
import json
import hashlib
import requests
import feedparser # type: ignore
import dateutil.parser
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from decouple import config

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone
from django.db import IntegrityError

from newsclip.discovery import discover_client_sources, fetch_sitemap_endpoint
from newsclip.models import Client, Article, Source, SourceEndpoint, FetchLog
from newsclip.providers import fetch_gdelt, fetch_youtube
from newsclip.source_seeds import ESSENTIAL_NEWS_SOURCES
from newsclip.utils import (
    build_client_search_queries,
    build_essential_source_queries,
    client_context_terms,
    client_positive_terms,
    record_endpoint_failure,
    record_endpoint_success,
    sanitize_sensitive_text,
    save_article,
)

from newsapi import NewsApiClient # type: ignore
import re

# Constantes
MAX_NEWSAPI_DAYS = 30
LOOKBACK_DAYS = 90
MAX_API_PAGES = config("NEWS_FETCH_MAX_PAGES", default=5, cast=int)
MAX_GOOGLE_RSS_QUERIES = config("GOOGLE_RSS_MAX_QUERIES", default=20, cast=int)
MAX_GOOGLE_RSS_ESSENTIAL_SOURCE_QUERIES = config("GOOGLE_RSS_ESSENTIAL_SOURCE_QUERIES", default=24, cast=int)
GOOGLE_RSS_REQUEST_TIMEOUT = config("GOOGLE_RSS_REQUEST_TIMEOUT", default=12, cast=int)
GOOGLE_RSS_WORKERS = config("GOOGLE_RSS_WORKERS", default=4, cast=int)
GOOGLE_RSS_QUICK_MAX_QUERIES = config("GOOGLE_RSS_QUICK_MAX_QUERIES", default=8, cast=int)
GOOGLE_RSS_QUICK_ESSENTIAL_SOURCE_QUERIES = config("GOOGLE_RSS_QUICK_ESSENTIAL_SOURCE_QUERIES", default=18, cast=int)
BRAVE_SEARCH_QUICK_MAX_QUERIES = config("BRAVE_SEARCH_QUICK_MAX_QUERIES", default=3, cast=int)
BRAVE_SEARCH_QUICK_RESULTS_PER_QUERY = config("BRAVE_SEARCH_QUICK_RESULTS_PER_QUERY", default=10, cast=int)

# Variáveis de API lidas do .env ou ambiente
NEWSDATA_KEY = config("NEWSDATA_API_KEY", default=None)
NEWSDATA_URL = config("NEWSDATA_URL", default="https://newsdata.io/api/1/latest")
NEWSAPI_KEY = config("NEWSAPI_API_KEY", default=None)

def strip_accents(s: str) -> str:
    if not s: return ""
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_for_match(value: str) -> str:
    """Normaliza acentos, caixa e espaços sem deformar a consulta enviada à fonte."""
    return re.sub(r"\s+", " ", strip_accents(value or "").casefold()).strip()

def contains_keyword(text: str, keywords) -> bool:
    normalized_text = normalize_for_match(text)
    return any(normalize_for_match(keyword) in normalized_text for keyword in keywords)

def build_advanced_query(keywords, operators=None):
    if not keywords: return ""
    if not operators:
        return " OR ".join(f'"{kw}"' if ' ' in kw else kw for kw in keywords)
    
    parts = []
    for i, kw in enumerate(keywords):
        if i > 0:
            op = 'OR' 
            if isinstance(operators, dict) and keywords[i-1] in operators:
                 op = operators[keywords[i-1]]
            parts.append(op)
        parts.append(f'"{kw}"' if ' ' in kw else kw)
    return ' '.join(parts)

def build_query_batches(keywords, max_length):
    """Divide termos em consultas aceitas pelas APIs sem descartar palavras-chave."""
    batches = []
    current = []
    for keyword in keywords:
        token = f'"{keyword}"' if ' ' in keyword else keyword
        candidate = " OR ".join([*current, token])
        if current and len(candidate) > max_length:
            batches.append(" OR ".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        batches.append(" OR ".join(current))
    return batches


def ensure_essential_news_sources():
    for seed in ESSENTIAL_NEWS_SOURCES:
        url = seed["url"]
        domain = (urlparse(url).hostname or seed.get("site", "")).removeprefix("www.")
        source, _created = Source.objects.get_or_create(
            url=url,
            defaults={
                "name": seed["name"],
                "domain": domain,
                "source_type": "DISCOVERED",
                "is_active": True,
                "status": "ACTIVE",
                "discovered_automatically": False,
                "discovery_provider": "SEED",
                "confidence_score": 100,
            },
        )
        if source.status in {"BLOCKED", "DISCARDED"}:
            continue
        updates = {}
        if source.name != seed["name"]:
            updates["name"] = seed["name"]
        if not source.domain:
            updates["domain"] = domain
        if not source.is_active:
            updates["is_active"] = True
        if source.status != "ACTIVE":
            updates["status"] = "ACTIVE"
        if source.confidence_score < 90:
            updates["confidence_score"] = 100
        if updates:
            Source.objects.filter(pk=source.pk).update(**updates)


class Command(BaseCommand):
    help = "Busca notícias para cada cliente e salva as novas entradas"

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, help="ID do cliente para filtrar")
        parser.add_argument(
            "--force-run", action="store_true",
            help="Força a execução de fetchers de API mesmo que as chaves não pareçam configuradas.",
        )
        parser.add_argument(
            "--quick", action="store_true",
            help="Executa uma busca rápida para uso interativo no painel.",
        )

    def log(self, message, level='INFO', client=None, source=None):
        """Helper para logar no stdout e no banco"""
        message = sanitize_sensitive_text(message)
        style_func = self.style.SUCCESS if level == 'SUCCESS' else (self.style.ERROR if level == 'ERROR' else self.style.WARNING if level == 'WARNING' else self.style.NOTICE)
        
        # Print no console
        if level == 'ERROR':
            self.stderr.write(style_func(message))
        else:
            self.stdout.write(style_func(message))
            
        # Salvar no banco
        try:
            FetchLog.objects.create(
                client=client,
                source=source,
                level=level,
                message=message
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro ao salvar log no banco: {e}"))

    def handle(self, *args, **options):
        client_id = options.get("client_id")
        force_run = options.get("force_run", False)
        quick_run = options.get("quick", False)
        clients = Client.objects.filter(id=client_id) if client_id else Client.objects.all()

        if not clients.exists():
            self.log("Nenhum cliente encontrado para processar.", level='WARNING')
            return

        ensure_essential_news_sources()
        utc_now = dj_timezone.now()
        since_dt = utc_now - timedelta(days=LOOKBACK_DAYS)
        overall_total = 0

        for client in clients:
            self.log(f"--- Processando cliente: {client.name} ---", client=client)
            # Termos separados por função: identidade forte fica no perfil do cliente;
            # termos complementares/legados entram apenas como contexto.
            kws = client_context_terms(client)
            search_queries = build_client_search_queries(
                client,
                max_queries=max(MAX_GOOGLE_RSS_QUERIES, 20),
            )
            essential_source_queries = build_essential_source_queries(
                client,
                max_sources=max(1, MAX_GOOGLE_RSS_ESSENTIAL_SOURCE_QUERIES),
            )

            if not search_queries:
                self.log(f"Cliente {client.name}: sem identidade de busca definida. Pulando.", level='WARNING', client=client)
                continue

            match_terms = client_positive_terms(client)

            discovery_stats = {
                "queries": 0,
                "results": 0,
                "relevant": 0,
                "new_sources": 0,
                "articles": 0,
            }
            if quick_run:
                discovery_stats = discover_client_sources(
                    client,
                    kws,
                    log=self.log,
                    force=force_run,
                    max_queries=BRAVE_SEARCH_QUICK_MAX_QUERIES,
                    results_per_query=BRAVE_SEARCH_QUICK_RESULTS_PER_QUERY,
                    profile_limit=0,
                )
            else:
                discovery_stats = discover_client_sources(client, kws, log=self.log, force=force_run)
            if discovery_stats["queries"]:
                self.log(
                    "Descoberta Brave: "
                    f"{discovery_stats['queries']} consultas, "
                    f"{discovery_stats['results']} resultados, "
                    f"{discovery_stats['relevant']} relevantes, "
                    f"{discovery_stats['new_sources']} novas fontes e "
                    f"{discovery_stats['articles']} noticias novas.",
                    level='SUCCESS',
                    client=client,
                )
            
            futures_map = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 1. APIs Pagas (NewsAPI, NewsData)
                if not quick_run and (NEWSAPI_KEY or force_run):
                    futures_map[executor.submit(self.fetch_newsapi, client, search_queries, since_dt, utc_now)] = "NewsAPI"
                elif not quick_run:
                    self.log(f"NewsAPI KEY não configurada. Pulando.", level='WARNING', client=client)

                if not quick_run and (NEWSDATA_KEY or force_run):
                    futures_map[executor.submit(self.fetch_newsdata, client, search_queries, since_dt, utc_now)] = "NewsData"
                elif not quick_run:
                    self.log(f"NewsData KEY não configurada. Pulando.", level='WARNING', client=client)
                
                # 2. Google RSS (Busca Dinâmica)
                # Buscas comuns e fontes essenciais rodam em lotes separados.
                # Assim, consultas site:g1/site:diario/etc. nunca são cortadas
                # pelo limite das queries comuns e a coleta não fica presa em
                # uma sequência longa de requests.
                futures_map[
                    executor.submit(
                        self.fetch_google_rss,
                        client,
                        search_queries,
                        since_dt,
                        max_queries=GOOGLE_RSS_QUICK_MAX_QUERIES if quick_run else MAX_GOOGLE_RSS_QUERIES,
                    )
                ] = "GoogleRSS"
                if essential_source_queries:
                    futures_map[
                        executor.submit(
                            self.fetch_google_rss,
                            client,
                            essential_source_queries,
                            since_dt,
                            max_queries=(
                                GOOGLE_RSS_QUICK_ESSENTIAL_SOURCE_QUERIES
                                if quick_run
                                else MAX_GOOGLE_RSS_ESSENTIAL_SOURCE_QUERIES
                            ),
                        )
                    ] = "GoogleRSS fontes essenciais"

                if not quick_run and getattr(settings, "GDELT_ENABLED", True):
                    futures_map[executor.submit(fetch_gdelt, client, kws, since_dt, self.log)] = "GDELT"

                if getattr(settings, "YOUTUBE_API_KEY", "") or client.youtube:
                    futures_map[executor.submit(fetch_youtube, client, kws, since_dt, self.log)] = "YouTube"

                # 3. Fontes do Banco de Dados (RSS e Scrape)
                # No modo rápido do painel, evitamos feeds/sitemaps descobertos:
                # feedparser.parse(url) pode ficar preso em rede e deixar o botão
                # aguardando por vários minutos. A coleta completa continua
                # disponível pelo comando normal/agendado.
                if not quick_run:
                    active_sources = Source.objects.filter(is_active=True)
                    for source in active_sources:
                        if source.source_type == 'RSS':
                            futures_map[executor.submit(self.fetch_single_rss, client, source, match_terms, since_dt)] = f"RSS: {source.name}"
                        elif source.source_type == 'SCRAPE':
                            futures_map[executor.submit(self.fetch_single_scrape, client, source, match_terms)] = f"Scrape: {source.name}"

                    active_endpoints = SourceEndpoint.objects.filter(
                        is_active=True,
                        source__is_active=True,
                    ).select_related("source")
                    for endpoint in active_endpoints:
                        if endpoint.endpoint_type == "RSS":
                            futures_map[executor.submit(self.fetch_endpoint_rss, client, endpoint, match_terms, since_dt)] = f"RSS descoberto: {endpoint.source.name}"
                        elif endpoint.endpoint_type in {"SITEMAP", "NEWS_SITEMAP"}:
                            futures_map[executor.submit(fetch_sitemap_endpoint, self, client, endpoint, match_terms, since_dt)] = f"Sitemap: {endpoint.source.name}"
                
                client_total_saved = discovery_stats["articles"]
                for future in as_completed(futures_map):
                    source_name = futures_map[future]
                    try:
                        num_saved = future.result()
                        if num_saved > 0:
                            self.log(f"Fonte {source_name}: {num_saved} notícia(s) salva(s).", level='SUCCESS', client=client)
                        client_total_saved += num_saved
                    except Exception as e:
                        self.log(f"ERRO na fonte {source_name}: {e}", level='ERROR', client=client)

            if client_total_saved > 0:
                self.log(f"Total de {client_total_saved} notícia(s) salva(s) para {client.name}.", level='SUCCESS', client=client)
            else:
                self.log(f"Nenhuma notícia nova salva para {client.name}.", level='INFO', client=client)
            overall_total += client_total_saved

        self.log(f"Execução Finalizada. Total geral: {overall_total}", level='SUCCESS')

    def _get_content_from_entry(self, entry):
        if hasattr(entry, 'content') and entry.content:
            if isinstance(entry.content, list) and len(entry.content) > 0 and hasattr(entry.content[0], 'value') and entry.content[0].value:
                return entry.content[0].value
        if hasattr(entry, 'summary') and entry.summary:
            return entry.summary
        if hasattr(entry, 'description') and entry.description:
            return entry.description
        return None

    def fetch_newsdata(self, client, keywords, since_dt, until_dt):
        count_saved = 0
        if not NEWSDATA_KEY: return 0

        try:
            # NewsData impõe um limite curto para q; lotes evitam erro 422 em
            # clientes com muitos termos sem multiplicar uma chamada por termo.
            for query in build_query_batches(keywords, max_length=90):
                params = {
                    'apikey': NEWSDATA_KEY, 'q': query, 'language': 'pt',
                    'from_date': since_dt.strftime('%Y-%m-%d'),
                    'to_date': until_dt.strftime('%Y-%m-%d'),
                }
                response = requests.get(NEWSDATA_URL, params=params, timeout=30)
                if response.status_code == 422:
                    error_message = response.json().get('results', {}).get('message', response.text)
                    if "from_date" in error_message:
                        params.pop('from_date', None)
                        params.pop('to_date', None)
                        response = requests.get(NEWSDATA_URL, params=params, timeout=30)

                response.raise_for_status()
                data = response.json()
                for _page_number in range(MAX_API_PAGES):
                    articles = data.get('results', [])
                    for item in articles:
                        url = item.get('link') or item.get('source_url')
                        title = item.get('title')
                        if not url or not title: continue
                        content_text = item.get('content') or item.get('description')
                        created = save_article(
                            client=client, title=title, url=url, raw_date=item.get('pubDate'),
                            source=item.get('source_id') or "NewsData.io", content_text=content_text,
                            provider="NEWSDATA",
                            query=query,
                        )
                        count_saved += int(created is not None)

                    next_page = data.get("nextPage")
                    if not next_page:
                        break
                    params["page"] = next_page
                    response = requests.get(NEWSDATA_URL, params=params, timeout=30)
                    response.raise_for_status()
                    data = response.json()
        except Exception as e:
            self.log(f"Erro NewsData: {e}", level='ERROR', client=client)
        return count_saved

    def fetch_google_rss(self, client, keywords_list, since_dt, max_queries=None):
        count_saved = 0
        if not keywords_list: return 0
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; ClippingApp/1.0)"}
            # Consultas separadas evitam que uma expressão OR longa seja truncada
            # e aumentam a cobertura de termos com volumes muito diferentes.
            selected_keywords = list(dict.fromkeys(keywords_list))[: max_queries or MAX_GOOGLE_RSS_QUERIES]

            def fetch_one(keyword):
                saved_for_keyword = 0
                try:
                    query_string = f'{keyword} when:{LOOKBACK_DAYS}d'
                    rss_url = f"https://news.google.com/rss/search?hl=pt-BR&gl=BR&ceid=BR:pt-BR&q={quote_plus(query_string)}"
                    response = requests.get(rss_url, headers=headers, timeout=GOOGLE_RSS_REQUEST_TIMEOUT)
                    response.raise_for_status()
                    feed = feedparser.parse(response.content)
                except Exception as exc:
                    self.log(f"Google RSS falhou para o termo '{keyword}': {exc}", level='WARNING', client=client)
                    return 0

                for entry in feed.entries:
                    url = entry.get('link')
                    title = entry.get('title')
                    if not url or not title: continue

                    pub_date_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                    publication_date = None
                    if pub_date_parsed:
                        try:
                            dt_naive = datetime.fromtimestamp(time.mktime(pub_date_parsed))
                            publication_date = dj_timezone.make_aware(dt_naive, timezone.utc) if dj_timezone.is_naive(dt_naive) else dt_naive
                        except (OverflowError, OSError, ValueError):
                            publication_date = None

                    if publication_date and publication_date < since_dt:
                        continue

                    content_text = self._get_content_from_entry(entry)
                    created = save_article(
                        client=client, title=title, url=url,
                        raw_date=publication_date.isoformat() if publication_date else None,
                        source=entry.get('source', {}).get('title') or "Google News",
                        content_text=content_text,
                        provider="GOOGLE_RSS",
                        query=keyword,
                    )
                    saved_for_keyword += int(created is not None)
                return saved_for_keyword

            worker_count = max(1, min(GOOGLE_RSS_WORKERS, len(selected_keywords) or 1))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(fetch_one, keyword) for keyword in selected_keywords]
                for future in as_completed(futures):
                    count_saved += future.result()
        except Exception as e:
            self.log(f"Erro Google RSS: {e}", level='ERROR', client=client)
        return count_saved

    def fetch_single_rss(self, client, source_obj, keywords_list, since_date_aware):
        return self._fetch_rss_url(client, source_obj, source_obj.url, keywords_list, since_date_aware)

    def fetch_endpoint_rss(self, client, endpoint, keywords_list, since_date_aware):
        try:
            count = self._fetch_rss_url(
                client, endpoint.source, endpoint.url, keywords_list, since_date_aware
            )
            record_endpoint_success(endpoint)
            return count
        except Exception as exc:
            record_endpoint_failure(endpoint, exc, client=client, log=self.log)
            raise

    def _fetch_rss_url(self, client, source_obj, feed_url, keywords_list, since_date_aware):
        count_saved = 0
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                url = entry.get('link')
                title = entry.get('title')
                if not url or not title: continue
                content_text = self._get_content_from_entry(entry)
                searchable_text = BeautifulSoup(
                    f"{title} {content_text or ''}", "html.parser"
                ).get_text(" ", strip=True)
                if not contains_keyword(searchable_text, keywords_list): continue
                
                pub_date_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                publication_date_aware = None
                if pub_date_parsed:
                    try:
                        dt_naive = datetime.fromtimestamp(time.mktime(pub_date_parsed))
                        publication_date_aware = dj_timezone.make_aware(dt_naive, timezone.utc) if dj_timezone.is_naive(dt_naive) else dt_naive
                    except: publication_date_aware = dj_timezone.now() 
                
                if publication_date_aware and publication_date_aware < since_date_aware: continue
                
                source_name = source_obj.name
                created = save_article(client=client, title=title, url=url,
                                       raw_date=publication_date_aware.isoformat() if publication_date_aware else None,
                                       source=source_name, content_text=content_text, provider="RSS",
                                       query=feed_url)
                count_saved += int(created is not None)
        except Exception as e:
            self.log(f"Erro RSS {source_obj.name}: {e}", level='ERROR', client=client, source=source_obj)
        return count_saved

    def fetch_single_scrape(self, client, source_obj, keywords_list):
        count_saved = 0
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'}
        try:
            response = requests.get(source_obj.url, headers=headers, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Se não tiver seletores definidos, tenta pegar tudo (arriscado, mas fallback)
            # Idealmente deve ter seletores
            if not source_obj.title_selector:
                return 0

            article_blocks = [soup] # Simplificação: assume que a página é uma lista ou busca no corpo todo
            # Se tiver um seletor de container/item, usaria aqui. Como o modelo simplificado não tem 'item_selector',
            # vamos buscar os títulos diretamente e tentar achar o link parente/próximo.
            
            # Melhor abordagem genérica sem item_selector: buscar todos os elementos que casam com title_selector
            titles = soup.select(source_obj.title_selector)
            
            for title_tag in titles:
                title = title_tag.get_text(strip=True)
                if not title or not contains_keyword(title, keywords_list): continue
                
                # Tenta achar o link: ou é o próprio tag, ou um pai, ou um filho
                link_tag = None
                if title_tag.name == 'a': link_tag = title_tag
                else:
                    link_tag = title_tag.find_parent('a') or title_tag.find('a')
                
                # Se tiver seletor específico de link, usa ele (assumindo que seja relativo ao container, o que complica sem container definido)
                # Vamos manter simples: se achou título e link, salva.
                
                article_url = None
                if link_tag:
                    article_url = link_tag.get('href')
                elif source_obj.link_selector:
                     # Tentativa de buscar link separado (muito frágil sem container)
                     pass

                if not article_url: continue
                
                article_url = urljoin(source_obj.url, article_url)
                
                created = save_article(client=client, title=title, url=article_url, raw_date=None,
                                       source=source_obj.name, content_text=None, provider="SCRAPE",
                                       query=source_obj.url)
                count_saved += int(created is not None)

        except Exception as e:
            self.log(f"Erro Scrape {source_obj.name}: {e}", level='ERROR', client=client, source=source_obj)
        return count_saved

    def fetch_newsapi(self, client, keywords, since_date_aware, until_date_aware):
        count_saved = 0
        if not NEWSAPI_KEY: return 0
        if not keywords: return 0

        api = NewsApiClient(api_key=NEWSAPI_KEY)
        domains_for_api = ','.join(d.strip() for d in client.domains.split(',')) if client.domains else None

        try:
            newsapi_since = max(since_date_aware, until_date_aware - timedelta(days=MAX_NEWSAPI_DAYS))
            for query_string in build_query_batches(keywords, max_length=450):
                for page in range(1, MAX_API_PAGES + 1):
                    all_articles_response = api.get_everything(
                        q=query_string, domains=domains_for_api,
                        from_param=newsapi_since.strftime('%Y-%m-%d'),
                        to=until_date_aware.strftime('%Y-%m-%d'),
                        language='pt', sort_by='publishedAt', page_size=100, page=page,
                    )

                    articles = all_articles_response.get('articles', [])
                    for article_data in articles:
                        url = article_data.get('url')
                        title = article_data.get('title')
                        if not url or not title: continue

                        content_text = article_data.get('description')
                        source_name = article_data.get('source', {}).get('name') or "NewsAPI"
                        created = save_article(
                            client=client, title=title, url=url, raw_date=article_data.get('publishedAt'),
                            source=source_name, content_text=content_text,
                            provider="NEWSAPI",
                            query=query_string,
                        )
                        count_saved += int(created is not None)

                    if len(articles) < 100:
                        break
        except Exception as e:
            self.log(f"Erro NewsAPI: {e}", level='ERROR', client=client)
        return count_saved
          

