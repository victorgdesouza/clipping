# newsclip/utils.py

import re
import hashlib
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from pathlib import Path
from collections import Counter
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone as dj_timezone
# from googlesearch import search  # Temporarily disabled - requires distutils (removed in Python 3.14)
from dateutil import parser as date_parser

# Importações adicionadas para SearchVector
from django.contrib.postgres.search import SearchVector
from django.db import connection
from django.db.models import Value # Para tratar campos potencialmente nulos no SearchVector

from newsclip.models import Article


# —————————————————————————————————————————
# 1) Summary extractivo rápido (NLTK)
# —————————————————————————————————————————

# ATENÇÃO: Execute uma única vez:
# pip install nltk
# python -m nltk.downloader punkt stopwords


def generate_summary(text: str, num_sentences: int = 3) -> str:
    # resumo extractivo simples: pega as N primeiras sentenças
    # Idealmente, este resumo deveria ser do conteúdo do artigo, não do título.
    if not text: # Adicionado para evitar erro se text for None ou vazio
        return ""
    sentences = text.split('.')
    summary = '.'.join(sentences[:num_sentences]).strip()
    if summary and not summary.endswith('.'): # Adicionado para garantir que termina com ponto se não vazio
        summary += '.'
    return summary


# —————————————————————————————————————————
# 2) Busca no Google via GPT + googlesearch
# —————————————————————————————————————————

# —————————————————————————————————————————
# 2) Busca no Google via GPT + googlesearch
# —————————————————————————————————————————

import requests

def search_google_api(query, api_key, cse_id, num_results=10, **kwargs):
    """
    Realiza busca usando a Google Custom Search JSON API.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'key': api_key,
        'cx': cse_id,
        'num': min(num_results, 10), # API limita a 10 por página
        'lr': 'lang_pt',
        **kwargs
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        items = data.get('items', [])
        return [item['link'] for item in items]
    except Exception as e:
        print(f"Erro na Google API: {e}")
        return []

def buscar_com_google(queries: list[str], num_results: int = 10) -> list[str]:
    urls = []
    
    # Verificar se temos chaves de API configuradas
    api_key = getattr(settings, 'GOOGLE_API_KEY', None)
    cse_id = getattr(settings, 'GOOGLE_CSE_ID', None)
    use_api = bool(api_key and cse_id)

    for q in queries:
        try:
            if use_api:
                # Usar API Oficial
                print(f"Buscando via Google API: {q}")
                results = search_google_api(q, api_key, cse_id, num_results=num_results)
                urls.extend(results)
            else:
                # Fallback para Scraping (googlesearch-python)
                print(f"Buscando via Scraping (googlesearch): {q}")
                for url_result in search(q, num_results=num_results, lang="pt"):
                    urls.append(url_result)
                    
        except Exception as e:
            print(f"Erro ao buscar no Google para query '{q}': {e}")
            
    return list(set(urls)) # Remove duplicatas


# —————————————————————————————————————————
# 3) Classificação de tópico simples
# —————————————————————————————————————————

class SimpleTopicClassifier:
    def __init__(self):
        self.topic_keywords = {
            "Política": ["presidente","governo","ministro","senado","câmara","política", "deputado", "lei", "eleição"],
            "Economia": ["economia","inflação","juros","pib","comércio","financeiro", "dólar", "bolsa"],
            "Esportes": ["jogo","time","futebol","campeonato","esportes","olímpico", "atleta", "vitória", "derrota"],
            "Tecnologia": ["tecnologia","startup","inovação","software","hardware","internet", "app", "ia"],
            "Cultura": ["cultura","música","filme","arte","literatura","teatro", "show", "exposição"],
            "Saúde": ["saúde","hospital","vacina","doença","médico","tratamento", "pandemia", "oms"],
            # Adicionar mais tópicos e palavras-chave conforme necessário
        }

    def classify(self, text: str) -> str:
        if not text: # Adicionado para evitar erro se text for None ou vazio
            return "Sem classificação"
        text_low = text.lower()
        scores = {
            topic: sum(text_low.count(kw) for kw in kws)
            for topic, kws in self.topic_keywords.items()
        }
        # Verifica se há algum score maior que zero para evitar erro com max() em lista vazia ou só com zeros
        if not any(s > 0 for s in scores.values()):
            return "Sem classificação"

        best, val = max(scores.items(), key=lambda x: x[1])
        return best # Removido 'if val > 0' pois já verificado acima

_topic_clf = SimpleTopicClassifier()


TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}


def normalize_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


def canonicalize_article_url(value: str) -> str:
    parts = urlsplit((value or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return (value or "").strip()
    host = parts.hostname.casefold()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit((parts.scheme.casefold(), f"{host}{port}", path, query, ""))


def article_dedup_key(title: str, source: str) -> str:
    normalized_source = normalize_match_text(source)
    normalized_title = normalize_match_text(title)
    # Google News costuma anexar " - Fonte" ao titulo. A fonte ja faz parte
    # da chave, portanto o sufixo deve ser removido antes do fingerprint.
    for separator in (" - ", " | ", " — ", " – "):
        suffix = f"{separator}{normalized_source}"
        if normalized_source and normalized_title.endswith(suffix):
            normalized_title = normalized_title[: -len(suffix)].strip()
            break
    normalized_title = re.sub(r"[^a-z0-9]+", " ", normalized_title).strip()
    payload = f"{normalized_source}|{normalized_title}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def client_excluded_terms(client) -> list[str]:
    return [
        term.strip()
        for term in (getattr(client, "excluded_keywords", "") or "").split(",")
        if term.strip()
    ]


def contains_excluded_term(client, *values: str) -> bool:
    searchable = normalize_match_text(" ".join(value or "" for value in values))
    return any(normalize_match_text(term) in searchable for term in client_excluded_terms(client))


def client_positive_terms(client) -> list[str]:
    values = [getattr(client, "name", "")]
    values.extend((getattr(client, "keywords", "") or "").split(","))
    result = []
    seen = set()
    for value in values:
        clean = value.strip()
        normalized = normalize_match_text(clean)
        if clean and normalized not in seen:
            result.append(clean)
            seen.add(normalized)
    return result


def validate_article_candidate(client, title: str, content: str, url: str, source: str) -> dict:
    if contains_excluded_term(client, title, content):
        return {"status": "REJECTED", "score": 0, "reason": "Contem termo excluido"}

    title_normalized = normalize_match_text(title)
    content_normalized = normalize_match_text(content)
    title_matches = []
    content_matches = []
    for term in client_positive_terms(client):
        normalized = normalize_match_text(term)
        if not normalized:
            continue
        if normalized in title_normalized:
            title_matches.append(term)
        elif normalized in content_normalized:
            content_matches.append(term)

    score = min(100, len(title_matches) * 70 + len(content_matches) * 35)
    if canonicalize_article_url(url).startswith("https://"):
        score = min(100, score + 5)
    trusted_domains = [item.strip().casefold() for item in (getattr(client, "domains", "") or "").split(",") if item.strip()]
    if any(domain in (url or "").casefold() for domain in trusted_domains):
        score = min(100, score + 10)

    if title_matches:
        reason = f"Termo no titulo: {title_matches[0]}"
    elif content_matches:
        reason = f"Termo no conteudo: {content_matches[0]}"
    else:
        reason = "Sem termo explicito no titulo ou resumo"
    return {
        "status": "ACCEPTED" if score >= 35 else "REVIEW",
        "score": score,
        "reason": reason,
    }


# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source, content_text=None, provider="OTHER"):
    """
    Salva um artigo no banco de dados e calcula seu search_vector.
    """
    dt = None
    if raw_date:
        try:
            parsed = date_parser.parse(str(raw_date))
            dt = parsed if parsed.tzinfo else dj_timezone.make_aware(
                parsed, dj_timezone.get_current_timezone()
            )
        except Exception as e:
            print(f"Erro ao parsear data '{raw_date}' para o título '{title[:50]}...': {e}. Usando None.")
            dt = None

    processed_title = (title or "")[:Article._meta.get_field('title').max_length]
    processed_source = (source or "")[:Article._meta.get_field('source').max_length]
    processed_url = canonicalize_article_url(url)

    validation = validate_article_candidate(
        client, processed_title, content_text or "", processed_url, processed_source
    )
    if validation["status"] == "REJECTED":
        return None

    dedup_key = article_dedup_key(processed_title, processed_source)
    
    summary_text = generate_summary(content_text if content_text else processed_title)
    topic_classification = _topic_clf.classify(processed_title) # _topic_clf deve estar definido neste arquivo

    article_instance = None
    try:
        if Article.objects.filter(client=client).filter(
            Q(url=processed_url) | Q(dedup_key=dedup_key)
        ).exists():
            return None

        with transaction.atomic():
            article_instance = Article.objects.create(
                client=client,
                url=processed_url,
                title=processed_title,
                published_at=dt,
                source=processed_source,
                summary=summary_text,
                topic=topic_classification,
                content=content_text if content_text else "",
                dedup_key=dedup_key,
                provider=(provider or "OTHER")[:32].upper(),
                relevance_score=validation["score"],
                validation_status=validation["status"],
                validation_reason=validation["reason"][:255],
            )
        # print(f"Artigo CRIADO: {article_instance.title_truncado}") # title_truncado é uma property no modelo Article

        if connection.vendor == "postgresql":
            # Grave um tsvector real; atribuir texto puro a SearchVectorField deixa
            # o índice inválido ou vazio no PostgreSQL.
            vector = (
                SearchVector("title", weight="A", config="portuguese")
                + SearchVector("summary", weight="B", config="portuguese")
                + SearchVector("content", weight="C", config="portuguese")
                + SearchVector("source", weight="D", config="portuguese")
            )
            Article.objects.filter(pk=article_instance.pk).update(search_vector=vector)
        else:
            article_instance.search_vector = " ".join(
                filter(None, [article_instance.title, article_instance.summary, article_instance.content, article_instance.source])
            )
            article_instance.save(update_fields=["search_vector"])
        # print(f"Search vector atualizado para: {article_instance.title_truncado}")

    except IntegrityError:
        # print(f"Artigo JÁ EXISTE (URL): {url}")
        pass
    except Exception as e:
        print(f"ERRO GERAL ao salvar artigo '{processed_title}' ({url}): {e}")

    return article_instance


