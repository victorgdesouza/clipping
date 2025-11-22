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

from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone
from django.db import IntegrityError

from newsclip.models import Client, Article, Source, FetchLog
from newsclip.utils import save_article

from newsapi import NewsApiClient # type: ignore
import re

# Constantes
MAX_NEWSAPI_DAYS = 30
LOOKBACK_DAYS = 90

# Variáveis de API lidas do .env ou ambiente
NEWSDATA_KEY = config("NEWSDATA_API_KEY", default=None)
NEWSDATA_URL = config("NEWSDATA_URL", default="https://newsdata.io/api/1/latest")
NEWSAPI_KEY = config("NEWSAPI_API_KEY", default=None)

def strip_accents(s: str) -> str:
    if not s: return ""
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

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

class Command(BaseCommand):
    help = "Busca notícias para cada cliente e salva as novas entradas"

    def add_arguments(self, parser):
        parser.add_argument("--client-id", type=int, help="ID do cliente para filtrar")
        parser.add_argument(
            "--force-run", action="store_true",
            help="Força a execução de fetchers de API mesmo que as chaves não pareçam configuradas.",
        )

    def log(self, message, level='INFO', client=None, source=None):
        """Helper para logar no stdout e no banco"""
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
        clients = Client.objects.filter(id=client_id) if client_id else Client.objects.all()

        if not clients.exists():
            self.log("Nenhum cliente encontrado para processar.", level='WARNING')
            return

        utc_now = dj_timezone.now()
        since_dt = utc_now - timedelta(days=LOOKBACK_DAYS)
        overall_total = 0

        for client in clients:
            self.log(f"--- Processando cliente: {client.name} ---", client=client)
            kws_raw = client.keywords or ""
            kws = [strip_accents(kw.strip().lower()) for kw in kws_raw.split(",") if kw.strip()]

            if not kws:
                self.log(f"Cliente {client.name}: sem keywords definidas. Pulando.", level='WARNING', client=client)
                continue
            
            api_query_string = build_advanced_query(kws, getattr(client, "search_operators", None))
            
            futures_map = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 1. APIs Pagas (NewsAPI, NewsData)
                if NEWSAPI_KEY or force_run:
                    futures_map[executor.submit(self.fetch_newsapi, client, api_query_string, since_dt, utc_now)] = "NewsAPI"
                else:
                    self.log(f"NewsAPI KEY não configurada. Pulando.", level='WARNING', client=client)

                if NEWSDATA_KEY or force_run:
                    futures_map[executor.submit(self.fetch_newsdata, client, api_query_string, since_dt, utc_now)] = "NewsData"
                else:
                    self.log(f"NewsData KEY não configurada. Pulando.", level='WARNING', client=client)
                
                # 2. Google RSS (Busca Dinâmica)
                futures_map[executor.submit(self.fetch_google_rss, client, kws, since_dt)] = "GoogleRSS"

                # 3. Fontes do Banco de Dados (RSS e Scrape)
                active_sources = Source.objects.filter(is_active=True)
                for source in active_sources:
                    if source.source_type == 'RSS':
                        futures_map[executor.submit(self.fetch_single_rss, client, source, kws, since_dt)] = f"RSS: {source.name}"
                    elif source.source_type == 'SCRAPE':
                        futures_map[executor.submit(self.fetch_single_scrape, client, source, kws)] = f"Scrape: {source.name}"
                
                client_total_saved = 0
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

    def fetch_newsdata(self, client, query, since_dt, until_dt):
        count_saved = 0
        if not NEWSDATA_KEY: return 0
        
        params = {
            'apikey': NEWSDATA_KEY, 'q': query, 'language': 'pt',
            'from_date': since_dt.strftime('%Y-%m-%d'),
            'to_date': until_dt.strftime('%Y-%m-%d'),
        }
        try:
            response = requests.get(NEWSDATA_URL, params=params, timeout=30)
            if response.status_code == 422:
                 error_message = response.json().get('results', {}).get('message', response.text)
                 if "from_date" in error_message:
                    params.pop('from_date', None)
                    params.pop('to_date', None)
                    response = requests.get(NEWSDATA_URL, params=params, timeout=30)
            
            response.raise_for_status()
            data = response.json()
            articles = data.get('results', [])
            
            for item in articles:
                url = item.get('link') or item.get('source_url')
                title = item.get('title')
                if not url or not title: continue
                content_text = item.get('content') or item.get('description')
                save_article(client=client, title=title, url=url, raw_date=item.get('pubDate'),
                             source=item.get('source_id') or "NewsData.io", content_text=content_text)
                count_saved += 1
        except Exception as e:
            self.log(f"Erro NewsData: {e}", level='ERROR', client=client)
        return count_saved

    def fetch_google_rss(self, client, keywords_list, since_dt):
        count_saved = 0
        if not keywords_list: return 0
        query_string = " OR ".join(f'"{kw}"' for kw in keywords_list)
        rss_url = f"https://news.google.com/rss/search?hl=pt-BR&gl=BR&ceid=BR:pt-BR&q={quote_plus(query_string)}"
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                url = entry.get('link')
                title = entry.get('title')
                if not url or not title: continue
                
                # REMOVIDO: Filtro estrito de título para permitir menções no corpo
                # title_lower = title.lower()
                # if not any(kw.lower() in title_lower for kw in keywords_list): continue
                
                pub_date_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                publication_date = None
                if pub_date_parsed:
                    try: 
                        dt_naive = datetime.fromtimestamp(time.mktime(pub_date_parsed))
                        publication_date = dj_timezone.make_aware(dt_naive, timezone.utc) if dj_timezone.is_naive(dt_naive) else dt_naive
                    except: publication_date = dj_timezone.now()
                
                # ADICIONADO: Filtro de data rigoroso
                if publication_date and publication_date < since_dt:
                    continue

                content_text = self._get_content_from_entry(entry)
                save_article(client=client, title=title, url=url,
                             raw_date=publication_date.isoformat() if publication_date else None,
                             source=entry.get('source', {}).get('title') or "Google News", content_text=content_text)
                count_saved += 1
        except Exception as e:
            self.log(f"Erro Google RSS: {e}", level='ERROR', client=client)
        return count_saved

    def fetch_single_rss(self, client, source_obj, keywords_list, since_date_aware):
        count_saved = 0
        try:
            feed = feedparser.parse(source_obj.url)
            for entry in feed.entries:
                url = entry.get('link')
                title = entry.get('title')
                if not url or not title: continue
                title_lower = title.lower()
                if not any(kw.lower() in title_lower for kw in keywords_list): continue
                
                pub_date_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                publication_date_aware = None
                if pub_date_parsed:
                    try:
                        dt_naive = datetime.fromtimestamp(time.mktime(pub_date_parsed))
                        publication_date_aware = dj_timezone.make_aware(dt_naive, timezone.utc) if dj_timezone.is_naive(dt_naive) else dt_naive
                    except: publication_date_aware = dj_timezone.now() 
                
                if publication_date_aware and publication_date_aware < since_date_aware: continue
                
                content_text = self._get_content_from_entry(entry)
                source_name = source_obj.name
                save_article(client=client, title=title, url=url,
                             raw_date=publication_date_aware.isoformat() if publication_date_aware else None,
                             source=source_name, content_text=content_text)
                count_saved += 1
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
                if not title or not any(kw.lower() in title.lower() for kw in keywords_list): continue
                
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
                
                save_article(client=client, title=title, url=article_url, raw_date=None,
                             source=source_obj.name, content_text=None)
                count_saved += 1

        except Exception as e:
            self.log(f"Erro Scrape {source_obj.name}: {e}", level='ERROR', client=client, source=source_obj)
        return count_saved

    def fetch_newsapi(self, client, query_string, since_date_aware, until_date_aware):
        count_saved = 0
        if not NEWSAPI_KEY: return 0
        if not query_string: return 0

        api = NewsApiClient(api_key=NEWSAPI_KEY)
        domains_for_api = ','.join(d.strip() for d in client.domains.split(',')) if client.domains else None

        try:
            all_articles_response = api.get_everything(
                q=query_string, domains=domains_for_api,
                from_param=since_date_aware.strftime('%Y-%m-%d'),
                to=until_date_aware.strftime('%Y-%m-%d'),
                language='pt', sort_by='relevancy', page_size=100
            )
            
            articles = all_articles_response.get('articles', [])
            for article_data in articles:
                url = article_data.get('url')
                title = article_data.get('title')
                if not url or not title: continue
                
                content_text = article_data.get('description')
                source_name = article_data.get('source', {}).get('name') or "NewsAPI"
                
                save_article(client=client, title=title, url=url, raw_date=article_data.get('publishedAt'),
                             source=source_name, content_text=content_text)
                count_saved += 1
        except Exception as e:
            self.log(f"Erro NewsAPI: {e}", level='ERROR', client=client)
        return count_saved
          

