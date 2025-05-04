import os
import time
import json
import hashlib
import requests
import feedparser
import dateutil.parser
import unicodedata
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.conf import settings
from newsclip.utils import gerar_consultas_com_gpt4all, buscar_com_google,save_article

from django.db import IntegrityError
from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone

from newsclip.models import Client, Article
from newsapi import NewsApiClient  # pip install newsapi-python
from newsclip.utils import generate_summary, SimpleTopicClassifier

# Quantos dias atrás a NewsAPI permite buscar no plano gratuito
MAX_NEWSAPI_DAYS = 30
# Quantos dias atrás olhar em todas as fontes
LOOKBACK_DAYS = 90


def strip_accents(s: str) -> str:
    """Remove acentos de uma string"""
    return ''.join(
        c for c in unicodedata.normalize('NFKD', s)
        if not unicodedata.combining(c)
    )


class SimpleCache:
    """Cache simples em arquivo para resultados de busca"""
    def __init__(self, cache_dir="/tmp/newsclip_cache", ttl_hours=6):
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        os.makedirs(self.cache_dir, exist_ok=True)

    def _key_path(self, key):
        return os.path.join(self.cache_dir, key)

    def _get_cache_key(self, query, source):
        return hashlib.md5(f"{query}:{source}".encode()).hexdigest()

    def get(self, query, source):
        path = self._key_path(self._get_cache_key(query, source))
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            entry = json.load(f)
        ts = datetime.fromisoformat(entry['timestamp'])
        if datetime.now() - ts > self.ttl:
            os.remove(path)
            return None
        return entry['content']

    def set(self, query, source, content):
        path = self._key_path(self._get_cache_key(query, source))
        entry = {'timestamp': datetime.now().isoformat(), 'content': content}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(entry, f)


cache = SimpleCache()
_topic_clf = SimpleTopicClassifier()

RSS_FEEDS = {
    "nacionais": {
        "grandes_portais": [
            "https://g1.globo.com/rss/g1/",
            "https://www.uol.com.br/rss/",
            "https://rss.folha.uol.com.br/emcimadahora/rss091.xml",
            "https://www.estadao.com.br/rss/",
            "https://www.cnnbrasil.com.br/feed/",
            "https://www.terra.com.br/rss/",
            "https://www.gazetadopovo.com.br/rss/",
            "https://www.noticiasaominuto.com.br/rss",
            "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
            "https://www.brasildefato.com.br/rss2.xml",
            "https://www.jornaldebrasilia.com.br/feed",
            "https://braziljournal.com/feed",
            "https://www.camara.leg.br/noticias/rss/noticias.xml",
            "https://res.stj.jus.br/hrestp-c-portalp/RSS.xml",
            "https://www.bcb.gov.br/rss/ultimasnoticias",
            "https://www.gov.br/pt-br/noticias/rss.xml"
        ],
        "regionais": [
            "https://diariodeolimpia.com.br/rss",
            "https://www.revistaeriopreto.com.br/feed",
            "https://www.opopular.com.br/rss",
            "https://www.acritica.com/rss",
            "https://www.jornaldocomercio.com/rss",
            "https://www.jornalnh.com.br/rss",
            "https://www.correiodopovo.com.br/rss",
            "https://www.jornaldacapital.com.br/rss"
        ],
        "sao_paulo": {
            "capital": [
                "https://noticias.r7.com/sao-paulo/rss.xml",
                "https://www.band.uol.com.br/sao-paulo/noticias/rss.xml",
                "https://www.metropoles.com/sao-paulo/feed"
            ],
            "sao_jose_do_rio_preto": [
                "https://www.diariodaregiao.com.br/rss",
                "https://www.sbtinterior.com/noticias/sao-jose-do-rio-preto/rss",
                "https://temmais.com/sao-jose-do-rio-preto-e-regiao/feed/",
                "https://www.acidadeon.com/riopreto/feed/"
            ],
            "olimpia": [
                "https://diariodeolimpia.com.br/rss"
            ],
            "interior": [
                "https://www.acidadeon.com/araraquara/feed/",
                "https://www.acidadeon.com/campinas/feed/",
                "https://jornalcidade.net/feed/",
                "https://www.liberal.com.br/rss/"
            ]
        },
        "minas_gerais": [
            "https://www.em.com.br/rss.xml",
            "https://www.itatiaia.com.br/rss/noticias",
            "https://www.otempo.com.br/rss",
            "https://www.hojeemdia.com.br/rss",
            "https://www.mg.supernoticia.com.br/rss"
        ],
        "rio_de_janeiro": [
            "https://g1.globo.com/rj/rss/g1-rj/feed.xml",
            "https://odia.ig.com.br/_Conteúdo/rss.xml",
            "https://extra.globo.com/rss.xml",
            "https://www.band.uol.com.br/rio-de-janeiro/noticias/rss.xml",
            "https://noticias.r7.com/rio-de-janeiro/rss.xml"
        ],
        "brasilia": [
            "https://correiobraziliense.webnode.com.br/rss/all.xml",
            "https://agenciabrasil.ebc.com.br/feed/"
        ],
        "economia": [
            "https://www.bcb.gov.br/rss/ultimasnoticias",
            "https://www.bcb.gov.br/rss/notas",
            "https://agenciabrasil.ebc.com.br/economia/feed",
            "https://br.investing.com/rss/news.rss",
            "https://br.investing.com/rss/news_285.rss",
            "https://rss.folha.uol.com.br/mercado/rss091.xml",
            "https://www.gazetadopovo.com.br/economia/feed/",
            "https://www.cepea.org.br/br/rss/indicadores.xml",
            "https://www.bloomberglinea.com.br/feed/",
            "https://valor.globo.com/rss"
        ],
        "tecnologia": [
            "https://news.google.com/rss/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNREUxWm5JU0JYQjBMVUpTS0FBUAE?hl=pt-BR&gl=BR&ceid=BR%3Apt-419",
            "https://canaltech.com.br/rss/",
            "https://www.tudocelular.com/rss/rss.xml",
            "https://www.nextpit.com.br/feed/main.xml",
            "https://tecnoblog.net/feed/",
            "https://macmagazine.com.br/feed/",
            "https://www.oficinadanet.com.br/rss",
            "https://g1.globo.com/dynamo/tecnologia/rss2.xml",
            "https://insideevs.uol.com.br/rss/articles/all/",
            "https://www.inovacaotecnologica.com.br/boletim/rss.php",
            "https://www.tecmundo.com.br/rss"
        ],
        "agro": [
            "https://www.noticiasagricolas.com.br/rss/",
            "https://www.noticiasagricolas.com.br/rss/cotacoes",
            "https://www.cepea.org.br/br/rss/agricola.xml",
            "https://www.canalrural.com.br/feed/",
            "https://summitagro.estadao.com.br/feed/",
            "https://www.embrapa.br/busca-de-noticias/-/asset_publisher/hMIqZUyfOUt3/rss?inheritRedirect=true"
        ],
        "politica": [
            "https://agenciabrasil.ebc.com.br/politica/feed",
            "https://www1.folha.uol.com.br/poder/rss091.xml",
            "https://www.gazetadopovo.com.br/republica/feed/",
            "https://www.camara.leg.br/noticias/rss/agencia",
            "https://www12.senado.leg.br/noticias/feed"
        ],
        "imobiliario": [
            "https://exame.com/invest/onde-investir/imoveis/feed/",
            "https://valor.globo.com/imoveis/rss"
        ],
        "parques_turismo": [
            "https://www.panrotas.com.br/rss/noticias",
            "https://g1.globo.com/dynamo/turismo-e-viagem/rss2.xml"
        ]
    },
    "internacionais": {
        "principais": [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://rss.cnn.com/rss/edition.rss",
            "https://www.reuters.com/rssFeed/topNews",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/america/portada",
            "https://rss.dw.com/rdf/rss-en-top",
            "https://www.voaportugues.com/rssfeeds",
            "https://www.latimes.com/feeds",
            "http://feeds.feedburner.com/vfdotcomrss",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.cnn.com/rss/edition_world.rss",
            "https://www.reuters.com/rssFeed/worldNews",
            "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada",
            "https://rss.dw.com/rdf/rss-en-world",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.nbcnews.com/nbcnews/public/news",
            "https://www.cnbc.com/id/100727362/device/rss/rss.html",
            "https://abcnews.go.com/abcnews/internationalheadlines",
            "https://www.cbsnews.com/latest/rss/world",
            "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
            "https://globalnews.ca/feed/",
            "https://news.sky.com/feeds/rss/world.xml"
        ]
    }
}


SCRAPE_SITES = [
    {
        "url": "https://www.camara.leg.br/noticias/",
        "title_selector": "h3.g-chamada__titulo",
        "link_selector": "h3.g-chamada__titulo a",
        "date_selector": "span.g-chamada__data",
    },
    {
        "url": "https://www12.senado.leg.br/noticias/ultimas",
        "title_selector": "h3.title",
        "link_selector": "h3.title a",
        "date_selector": "span.date",
    },
]

NEWSDATA_KEY = os.getenv("NEWSDATA_API_KEY")
NEWSDATA_URL = "https://newsdata.io/api/1/latest"
NEWSAPI_KEY = os.getenv("NEWSAPI_API_KEY")


def build_advanced_query(keywords, operators=None):
    """Monta query avançada com operadores OR padrão"""
    if not operators:
        return " OR ".join(f'"{kw}"' if ' ' in kw else kw for kw in keywords)
    parts = []
    for i, kw in enumerate(keywords):
        if i > 0:
            parts.append(operators.get(keywords[i-1], 'OR'))
        parts.append(f'"{kw}"' if ' ' in kw else kw)
    return ' '.join(parts)


class Command(BaseCommand):
    help = "Busca notícias para cada cliente e salva as novas entradas"

    def add_arguments(self, parser):
        parser.add_argument(
            "--client-id",
            type=int,
            help="ID do cliente para filtrar"
        )

    def handle(self, *args, **options):
        client_id = options.get("client_id")
        clients = (
            Client.objects.filter(id=client_id)
            if client_id else Client.objects.all()
        )

        utc_now = datetime.utcnow()
        since_dt = utc_now - timedelta(days=LOOKBACK_DAYS)
        overall_total = 0

        for client in clients:
            raw = [kw.strip() for kw in client.keywords.split(",") if kw.strip()]
            kws = [strip_accents(kw.strip('"').lower()) for kw in client.keywords.split(",") if kw.strip()]
            seen = set()
            if not kws:
                self.stdout.write(
                    self.style.WARNING(f"{client.name}: sem keywords")
                )
                continue

            seen = set()
            query = build_advanced_query(kws, getattr(client, 'operators', None))

        with ThreadPoolExecutor(max_workers=6) as exe:
            futures = {
                exe.submit(self.fetch_newsdata,   client, query, since_dt, utc_now, seen): "NewsData",
                exe.submit(self.fetch_google_rss, client, kws, seen):                 "GoogleRSS",
                exe.submit(self.fetch_rss_feeds,  client, kws, since_dt, seen):      "RSSFeeds",
                exe.submit(self.fetch_scrape,     client, kws, seen):                "WebScrape",
                exe.submit(self.fetch_llm_search, client, kws, seen):                "LLMGoogle",
            }
            total = 0
                           
            for fut in as_completed(futures):
                    src = futures[fut]
                    try:
                        cnt = fut.result()
                        total += cnt
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"{client.name} • {src}: {cnt} novas"
                            )
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{client.name} • {src} erro: {e}"
                            )
                        )

            overall_total += total
            self.stdout.write(
                self.style.SUCCESS(
                    f"{client.name}: total inseridas {total} notícias"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"🎉 Geral: {overall_total} notícias inseridas"
            )
        )

    def fetch_newsdata(self, client, query, since_dt, until_dt, seen):
        cnt = 0
        if not NEWSDATA_KEY:
            return cnt
        params = {
            'apikey': NEWSDATA_KEY,
            'q': query,
            'language': 'pt',
            'from_date': since_dt.strftime('%Y-%m-%d'),
            'to_date': until_dt.strftime('%Y-%m-%d'),
        }
        resp = requests.get(NEWSDATA_URL, params=params, timeout=30)
        data = resp.json() if resp.ok else {}
        for item in data.get('results', []):
            url = item.get('link') or item.get('url')
            if url and url not in seen:
                seen.add(url)
                save_article(
                    client,
                    item.get('title', '')[:300],
                    url,
                    item.get('pubDate'),
                    item.get('source_id') or item.get('source_name', '')
                )
                cnt += 1
        return cnt

    def fetch_google_rss(self, client, kws, seen):
        cnt = 0
        try:
            query = " OR ".join(f'"{kw}"' if ' ' in kw else kw for kw in kws)
            rss_url = (
                'https://news.google.com/rss/search?'
                'hl=pt-BR&gl=BR&ceid=BR:pt-150&q=' + quote_plus(query)
            )
            feed = feedparser.parse(rss_url)
            self.stdout.write(
                f"▶ GoogleRSS retornou {len(feed.entries)} itens para {client.name}"
            )
            for entry in feed.entries:
                title = strip_accents((entry.get('title') or '').strip().lower())
                url = entry.get('link')
                if not url or url in seen:
                    continue
                pub_struct = entry.get('published_parsed') or entry.get('updated_parsed')
                if not pub_struct:
                    continue
                pub_dt = datetime.fromtimestamp(
                    time.mktime(pub_struct), tz=timezone.utc
                )
                seen.add(url)
                save_article(
                    client,
                    entry.get('title', '')[:300],
                    url,
                    pub_dt.isoformat(),
                    entry.get('source', {}).get('title', '')
                )
                cnt += 1
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"{client.name} • GoogleRSS erro: {e}"
                )
            )
        return cnt

    def fetch_rss_feeds(self, client, kws, last_fetch_time, seen):
        cnt = 0
        last_fetch = (
            last_fetch_time.replace(tzinfo=timezone.utc)
            if last_fetch_time.tzinfo is None
            else last_fetch_time.astimezone(timezone.utc)
        )
        try:
            for rss_url in RSS_FEEDS:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries:
                    title = (entry.get('title') or '').strip()
                    if not any(kw in title.lower() for kw in kws):
                        continue
                    url = entry.get('link')
                    if not url or url in seen:
                        continue
                    pub_struct = (entry.get('published_parsed') or entry.get('updated_parsed'))
                    if not pub_struct:
                        continue
                    pub_dt = datetime.fromtimestamp(
                        time.mktime(pub_struct), tz=timezone.utc
                    )
                    if pub_dt <= last_fetch:
                        continue
                    seen.add(url)
                    save_article(
                        client,
                        title,
                        url,
                        pub_dt.isoformat(),
                        entry.get('source', {}).get('title', '')
                    )
                    cnt += 1
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"{client.name} • RSSFeeds erro: {e}"
                )
            )
        return cnt

    def fetch_scrape(self, client, kws, seen):
        cnt = 0
        headers = {'User-Agent': 'Mozilla/5.0'}
        for site in SCRAPE_SITES:
            try:
                r = requests.get(site['url'], headers=headers, timeout=15)
                r.raise_for_status()
            except Exception:
                continue
            time.sleep(1)
            soup = BeautifulSoup(r.text, 'html.parser')
            for block in soup.select(site['title_selector']):
                title = block.get_text(strip=True) or ''
                if not any(kw in title.lower() for kw in kws):
                    continue
                link_tag = block.select_one(site['link_selector'])
                if not link_tag:
                    continue
                url = link_tag.get('href')
                if not url or url in seen:
                    continue
                raw = None
                date_tag = block.select_one(site['date_selector'])
                if date_tag:
                    raw = date_tag.get_text(strip=True)
                seen.add(url)
                save_article(client, title, url, raw, site['url'])
                cnt += 1
        return cnt

    def fetch_newsapi(self, client, query, since_dt, until_dt, seen):
        cnt = 0
        if not NEWSAPI_KEY:
            return cnt
        limit_since = until_dt - timedelta(days=MAX_NEWSAPI_DAYS)
        since_dt_api = max(since_dt, limit_since)
        api = NewsApiClient(api_key=NEWSAPI_KEY)
        try:
            resp = api.get_everything(
                q=query,
                language='pt',
                from_param=since_dt_api.strftime('%Y-%m-%d'),
                to=until_dt.strftime('%Y-%m-%d'),
                sort_by='relevancy',
                page_size=100,
                domains=','.join(d.strip() for d in client.domains.split(',')) if client.domains else None
            )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(
                    f"NewsAPI pulado: {e}"
                )
            )
            return cnt
        for art in resp.get('articles', []):
            url = art.get('url')
            if not url or url in seen:
                continue
            seen.add(url)
            save_article(
                client,
                art.get('title', '')[:300],
                url,
                art.get('publishedAt'),
                art.get('source', {}).get('name', '')
            )
            cnt += 1
        return cnt

    def fetch_llm_search(self, client, kws, seen, max_queries=5, num_results=10):
        """
        Gera queries via LLM e busca no Google, bloqueia perfis do cliente
        e salva apenas URLs novas que contenham todas as kws exatas.
        """
        cnt = 0
        # 1) Gera e limpa consultas
        try:
            consultas = gerar_consultas_com_gpt4all(kws, max_queries)
            consultas = [q.replace("site:linkedin.com", "") for q in consultas]
            self.stdout.write(f"{client.name} • LLM: gerando {len(consultas)} consultas")
            urls = buscar_com_google(consultas, num_results=num_results)
            self.stdout.write(f"{client.name} • LLM retornou {len(urls)} URLs")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"{client.name} • LLMGoogle erro: {e}"))
            return 0

        # 2) Bloqueia perfis do próprio cliente
        banned = []
        if getattr(client, "instagram", None):
            banned.append(f"instagram.com/{client.instagram.lstrip('@')}")
        if getattr(client, "x", None):
            banned.append(f"x.com/{client.x.lstrip('@')}")
        if getattr(client, "youtube", None):
            banned.append(f"youtube.com/{client.youtube}")

        # 3) Itera URLs e salva
        for url in urls:
            if url in seen or any(b in url for b in banned):
                continue

            title = "(via LLM)"
            raw_date = None

            # Vídeo YouTube: extrai título/data sem warnings
            if "youtube.com/watch" in url or "youtu.be/" in url:
                try:
                    import yt_dlp
                    ydl_opts = {
                        'quiet': True,
                        'nocheckcertificate': True,
                        'ignore_warnings': True,
                        'no_warnings': True,
                    }
                    ydl = yt_dlp.YoutubeDL(ydl_opts)
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', title)
                    upload = info.get('upload_date')
                    if upload:
                        raw_date = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}T00:00:00"
                except Exception:
                    pass

            # 4) Garante que o título tenha todas as kws exatas
            words = title.lower().split()
            if not all(kw.lower() in words for kw in kws):
                continue

            # 5) Salva
            seen.add(url)
            save_article(client, title=title[:300], url=url, raw_date=raw_date, source="LLM/Google")
            cnt += 1

        self.stdout.write(self.style.SUCCESS(f"{client.name}: inseridas {cnt} notícias via LLM"))
        return cnt
