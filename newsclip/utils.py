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
from newsclip.source_seeds import ESSENTIAL_NEWS_SOURCES


SENSITIVE_QUERY_PARAM_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|key|token|access[_-]?token|subscription[_-]?key)=)([^&\s]+)"
)
SENSITIVE_HEADER_RE = re.compile(
    r"(?i)\b((?:x-subscription-token|authorization)\s*[:=]\s*)([^\s,;]+)"
)


def sanitize_sensitive_text(value: str) -> str:
    """Mascara segredos em textos de log/diagnóstico sem esconder o contexto do erro."""
    text = str(value or "")
    text = SENSITIVE_QUERY_PARAM_RE.sub(r"\1[REDACTED]", text)
    text = SENSITIVE_HEADER_RE.sub(r"\1[REDACTED]", text)
    return text


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


SOURCE_SUFFIX_HINTS = {
    "g1",
    "globo",
    "diario da regiao",
    "diario da regiao",
    "youtube",
    "google news",
    "google rss",
}


def normalized_article_title(title: str, source: str = "") -> str:
    normalized_source = normalize_match_text(source)
    normalized_title = normalize_match_text(title)
    # Google News costuma anexar " - Fonte" ao titulo. A fonte ja faz parte
    # da chave, portanto o sufixo deve ser removido antes do fingerprint.
    for separator in (" - ", " | ", " — ", " – "):
        suffix = f"{separator}{normalized_source}"
        if normalized_source and normalized_title.endswith(suffix):
            normalized_title = normalized_title[: -len(suffix)].strip()
            break
    for separator in (" - ", " | ", " — ", " – "):
        if separator in normalized_title:
            possible_title, possible_source = normalized_title.rsplit(separator, 1)
            cleaned_source = re.sub(r"[^a-z0-9]+", " ", possible_source).strip()
            if cleaned_source in SOURCE_SUFFIX_HINTS or len(cleaned_source.split()) <= 4:
                normalized_title = possible_title.strip()
                break
    return re.sub(r"[^a-z0-9]+", " ", normalized_title).strip()


def article_dedup_key(title: str, source: str = "") -> str:
    normalized_title = normalized_article_title(title, source)
    payload = f"story|{normalized_title}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def is_duplicate_article(client, title: str, source: str = "", url: str = "") -> bool:
    normalized_title = normalized_article_title(title, source)
    canonical_url = canonicalize_article_url(url)
    if not normalized_title and not canonical_url:
        return False

    candidates = Article.objects.filter(client=client)
    if canonical_url:
        candidates = candidates.filter(Q(url=canonical_url) | Q(title__isnull=False))
    for article in candidates.only("title", "source", "url"):
        if canonical_url and canonicalize_article_url(article.url) == canonical_url:
            return True
        if normalized_title and normalized_article_title(article.title, article.source) == normalized_title:
            return True
    return False


def deduplicate_articles_for_display(articles):
    seen = set()
    unique = []
    for article in articles:
        key = article_dedup_key(article.title, article.source)
        url_key = canonicalize_article_url(article.url)
        marker = key or url_key
        if marker in seen or (url_key and url_key in seen):
            continue
        seen.add(marker)
        if url_key:
            seen.add(url_key)
        unique.append(article)
    return unique


def client_excluded_terms(client) -> list[str]:
    return [
        term.strip()
        for term in (getattr(client, "excluded_keywords", "") or "").split(",")
        if term.strip()
    ]


def split_terms(value: str) -> list[str]:
    result = []
    seen = set()
    for item in re.split(r"[,\n;]+", value or ""):
        clean = re.sub(r"\s+", " ", item).strip()
        normalized = normalize_match_text(clean)
        if clean and normalized not in seen:
            result.append(clean)
            seen.add(normalized)
    return result


def social_handle_terms(client) -> list[str]:
    handles = []
    for field in ("instagram", "x", "youtube"):
        raw = (getattr(client, field, "") or "").strip()
        if not raw:
            continue
        handle = raw.rsplit("/", 1)[-1].strip().lstrip("@")
        if handle:
            handles.extend([handle, f"@{handle}"])
    return list(dict.fromkeys(handles))


PUBLIC_IDENTITY_PREFIXES = {
    "prefeito",
    "prefeita",
    "vereador",
    "vereadora",
    "deputado",
    "deputada",
    "senador",
    "senadora",
    "governador",
    "governadora",
    "secretario",
    "secretaria",
    "ministro",
    "ministra",
    "coronel",
}


GENERIC_CONTEXT_TERMS = {
    "agenda",
    "arena",
    "cidade",
    "evento",
    "festival",
    "gado",
    "ingressos",
    "noticias",
    "notícias",
    "pecuaria",
    "pecuária",
    "peao",
    "peão",
    "rodeio",
    "show",
    "touro",
}


def legacy_keyword_identity_terms(client) -> list[str]:
    """Promove aliases antigos que eram cadastrados em keywords como identidade.

    O campo keywords nasceu como campo único. Em cadastros antigos, ele ainda
    guarda termos que são identidade de pessoa pública/mandato, não apenas
    contexto. Sem essa ponte, buscas por clientes políticos ficam presas ao
    nome civil exato e perdem matérias que citam o cargo.
    """
    client_name_norm = normalize_match_text(getattr(client, "name", ""))
    name_tokens = {
        token
        for token in client_name_norm.split()
        if len(token) >= 4 and token not in {"sao", "são", "jose", "josé", "rio", "preto"}
    }
    promoted = []
    seen = set()

    for term in split_terms(getattr(client, "keywords", "")):
        normalized = normalize_match_text(term)
        words = normalized.split()
        if len(words) < 2:
            continue
        if normalized in GENERIC_CONTEXT_TERMS:
            continue

        starts_with_public_identity = bool(words and words[0] in PUBLIC_IDENTITY_PREFIXES)
        mentions_client_name = bool(name_tokens.intersection(words))
        is_public_identity_phrase = starts_with_public_identity and len(words) >= 3

        if not (mentions_client_name or is_public_identity_phrase):
            continue
        if normalized not in seen:
            promoted.append(term)
            seen.add(normalized)

    return promoted


def client_identity_terms(client) -> list[str]:
    values = [getattr(client, "name", "")]
    values.extend(split_terms(getattr(client, "name_variations", "")))
    values.extend(social_handle_terms(client))
    values.extend(legacy_keyword_identity_terms(client))
    result = []
    seen = set()
    for value in values:
        clean = re.sub(r"\s+", " ", value or "").strip()
        normalized = normalize_match_text(clean)
        if clean and normalized not in seen:
            result.append(clean)
            seen.add(normalized)
    return result


def strong_client_identity_terms(client) -> list[str]:
    """Termos que identificam o cliente com baixa chance de falso positivo."""
    terms = []
    for term in client_identity_terms(client):
        normalized = normalize_match_text(term)
        words = normalized.split()
        is_handle = term.strip().startswith("@") or any(
            normalized == normalize_match_text(handle).lstrip("@")
            for handle in social_handle_terms(client)
        )
        # Evita que uma palavra solta ou um recorte muito amplo vire identidade final.
        if is_handle or len(words) >= 2 or len(normalized) >= 12:
            terms.append(term)
    return terms


def client_context_terms(client) -> list[str]:
    values = []
    values.extend(split_terms(getattr(client, "context_terms", "")))
    # keywords permanece por compatibilidade, mas agora e contexto secundario.
    values.extend(split_terms(getattr(client, "keywords", "")))
    result = []
    seen = {normalize_match_text(item) for item in client_identity_terms(client)}
    for value in values:
        normalized = normalize_match_text(value)
        if value and normalized and normalized not in seen:
            result.append(value)
            seen.add(normalized)
    return result


def contains_excluded_term(client, *values: str) -> bool:
    searchable = normalize_match_text(" ".join(value or "" for value in values))
    return any(normalize_match_text(term) in searchable for term in client_excluded_terms(client))


def client_positive_terms(client) -> list[str]:
    return list(dict.fromkeys([*client_identity_terms(client), *client_context_terms(client)]))


def build_client_search_queries(client, max_queries: int = 20) -> list[str]:
    identities = client_identity_terms(client)
    contexts = client_context_terms(client)
    queries = []

    def add(query: str):
        clean = re.sub(r"\s+", " ", query or "").strip()
        if clean and clean not in queries:
            queries.append(clean)

    for identity in identities:
        quoted_identity = f'"{identity}"' if " " in identity else identity
        add(quoted_identity)
        add(f"{quoted_identity} noticias")
        for context in contexts[:6]:
            quoted_context = f'"{context}"' if " " in context else context
            add(f"{quoted_identity} {quoted_context}")

    # Nunca retorna apenas contexto solto. Contexto so aparece combinado com identidade.
    return queries[:max_queries]


def build_essential_source_queries(
    client,
    max_sources: int = 24,
    max_identities: int = 3,
) -> list[str]:
    """Gera buscas dirigidas para portais essenciais via operador site:."""
    identities = strong_client_identity_terms(client) or client_identity_terms(client)
    queries = []

    def add(query: str):
        clean = re.sub(r"\s+", " ", query or "").strip()
        if clean and clean not in queries:
            queries.append(clean)

    selected_identities = identities[:max_identities]
    for source in ESSENTIAL_NEWS_SOURCES[:max_sources]:
        site = source.get("site")
        if not site:
            continue
        for identity in selected_identities:
            quoted_identity = f'"{identity}"' if " " in identity else identity
            add(f"{quoted_identity} site:{site}")

    return queries


def trusted_source_references(client) -> list[tuple[str, str]]:
    references = []
    for item in split_terms(getattr(client, "domains", "")):
        parsed = urlsplit(item if "://" in item else f"https://{item}")
        host = (parsed.hostname or item).casefold()
        if host.startswith("www."):
            host = host[4:]
        path = (parsed.path or "").strip()
        if path and path != "/":
            path = "/" + path.strip("/")
        references.append((host, path))
    return references


def is_trusted_source(client, url: str, source: str = "") -> bool:
    parsed = urlsplit(url if "://" in (url or "") else f"https://{url or ''}")
    url_host = (parsed.hostname or "").casefold()
    if url_host.startswith("www."):
        url_host = url_host[4:]
    url_path = "/" + (parsed.path or "").strip("/")
    source_norm = normalize_match_text(source)
    for host, path in trusted_source_references(client):
        if host and (url_host == host or source_norm == normalize_match_text(host)):
            if not path or url_path.startswith(path):
                return True
    return False


def is_official_social_source(client, url: str, source: str = "") -> bool:
    searchable = normalize_match_text(f"{url} {source}")
    return any(normalize_match_text(handle) in searchable for handle in social_handle_terms(client))


def is_social_or_video_source(url: str, source: str = "", provider: str = "") -> bool:
    searchable = normalize_match_text(f"{url} {source} {provider}")
    social_markers = (
        "youtube.com",
        "youtu.be",
        "youtube",
        "instagram.com",
        "instagram",
        "facebook.com",
        "facebook",
        "tiktok.com",
        "tiktok",
        "x.com",
        "twitter.com",
    )
    return any(marker in searchable for marker in social_markers)


def matched_terms(searchable: str, terms: list[str]) -> list[str]:
    matches = []
    searchable_norm = normalize_match_text(searchable)
    for term in terms:
        normalized = normalize_match_text(term)
        if normalized and normalized in searchable_norm:
            matches.append(term)
    return matches


def audit_relevance_decision(
    client,
    *,
    provider: str = "",
    query: str = "",
    title: str = "",
    url: str = "",
    source: str = "",
    score: int = 0,
    reason: str = "",
    decision: str = "REJECTED",
):
    try:
        from newsclip.models import RelevanceAuditLog

        RelevanceAuditLog.objects.create(
            client=client,
            provider=(provider or "")[:50],
            query=query or "",
            title=(title or "")[:500],
            url=url or "",
            source=(source or "")[:255],
            relevance_score=max(0, min(int(score or 0), 100)),
            relevance_reason=(reason or "")[:255],
            decision=decision,
        )
    except Exception:
        # Auditoria nunca pode derrubar a coleta.
        pass


def validate_article_candidate(
    client,
    title: str,
    content: str,
    url: str,
    source: str,
    provider: str = "",
) -> dict:
    if contains_excluded_term(client, title, content, url, source):
        return {"status": "REJECTED", "score": 0, "reason": "Contem termo proibido"}

    identity_terms = client_identity_terms(client)
    strong_identity_terms = strong_client_identity_terms(client)
    context_terms = client_context_terms(client)
    searchable = " ".join([title or "", content or "", url or "", source or ""])
    visible_searchable = " ".join([title or "", url or "", source or ""])
    identity_matches = matched_terms(searchable, identity_terms)
    strong_identity_matches = matched_terms(searchable, strong_identity_terms)
    visible_identity_matches = matched_terms(visible_searchable, identity_terms)
    visible_strong_identity_matches = matched_terms(visible_searchable, strong_identity_terms)
    context_matches = matched_terms(searchable, context_terms)
    official_source = is_official_social_source(client, url, source)
    trusted_source = is_trusted_source(client, url, source)
    social_or_video_source = is_social_or_video_source(url, source, provider)

    full_name_norm = normalize_match_text(getattr(client, "name", ""))
    searchable_norm = normalize_match_text(searchable)
    visible_searchable_norm = normalize_match_text(visible_searchable)
    full_name_match = bool(full_name_norm and full_name_norm in searchable_norm)
    visible_full_name_match = bool(full_name_norm and full_name_norm in visible_searchable_norm)
    score = 0
    reason = "Sem identidade forte do cliente"

    if official_source:
        score = 100
        reason = "Origem oficial do cliente"
    elif full_name_match:
        score = 100
        reason = f"Nome oficial encontrado: {getattr(client, 'name', '')}"
    elif strong_identity_matches and context_matches:
        score = 85
        reason = f"Identidade forte + contexto: {strong_identity_matches[0]} + {context_matches[0]}"
    elif strong_identity_matches:
        score = 70
        reason = f"Identidade forte encontrada: {strong_identity_matches[0]}"
    elif identity_matches and context_matches:
        score = 55
        reason = f"Identidade fraca + contexto: {identity_matches[0]} + {context_matches[0]}"
    elif identity_matches:
        score = 40
        reason = f"Identidade fraca isolada: {identity_matches[0]}"
    elif trusted_source and len(context_matches) >= 2:
        score = 55
        reason = f"Fonte confiavel com contexto, mas sem identidade: {', '.join(context_matches[:2])}"
    elif len(context_matches) >= 2:
        normalized_matches = {normalize_match_text(item) for item in context_matches}
        person_context = any("paulo emilio" in item for item in normalized_matches)
        event_context = any(
            item in normalized_matches
            for item in {"rodeio", "evento", "touro", "peao", "arena", "ingressos", "show", "festival"}
        )
        if person_context and event_context:
            score = 55
            reason = f"Contexto ambiguo sem identidade: {', '.join(context_matches[:2])}"
        else:
            score = 35
            reason = f"Contexto sem identidade forte: {', '.join(context_matches[:2])}"
    elif context_matches:
        score = 35
        reason = f"Contexto isolado insuficiente: {context_matches[0]}"

    if social_or_video_source and not official_source and not (full_name_match or strong_identity_matches):
        score = min(score, 35)
        reason = f"{reason}; midia social/video nao oficial sem identidade forte"

    # Snippets de agregadores, especialmente Google News/RSS, podem conter termos
    # da consulta ou textos relacionados sem que a matéria em si seja sobre o
    # cliente. Para clipping final, identidade precisa aparecer no título, link
    # ou fonte — não apenas no resumo/conteúdo coletado.
    has_visible_identity = bool(
        official_source
        or visible_full_name_match
        or visible_strong_identity_matches
        or (visible_identity_matches and context_matches)
    )
    if not has_visible_identity and score >= 70:
        if trusted_source and strong_identity_matches:
            score = max(score, 75)
            reason = f"{reason}; identidade forte no snippet de fonte confiavel"
        else:
            score = 55
            reason = f"{reason}; identidade apenas no conteudo/snippet"

    if trusted_source and score >= 60:
        score = min(100, score + 10)
        reason = f"{reason}; fonte confiavel"

    if canonicalize_article_url(url).startswith("https://") and score >= 70:
        score = min(100, score + 3)

    if score >= 70:
        status = "ACCEPTED"
    elif score >= 40:
        status = "REVIEW"
    else:
        status = "REJECTED"

    return {
        "status": status,
        "score": score,
        "reason": reason,
    }


def revalidate_article(article, persist: bool = True, client=None) -> dict:
    article_client = client or article.client
    validation = validate_article_candidate(
        article_client,
        article.title,
        article.content or article.summary or "",
        article.url,
        article.source,
        provider=article.provider,
    )
    if persist and (
        article.validation_status != validation["status"]
        or article.relevance_score != validation["score"]
        or article.validation_reason != validation["reason"][:255]
    ):
        Article.objects.filter(pk=article.pk).update(
            validation_status=validation["status"],
            relevance_score=validation["score"],
            validation_reason=validation["reason"][:255],
        )
        article.validation_status = validation["status"]
        article.relevance_score = validation["score"]
        article.validation_reason = validation["reason"][:255]
    return validation


def revalidate_accepted_articles_for_client(client, limit: int = 250) -> int:
    articles = Article.objects.select_related("client").filter(
        client=client,
        excluded=False,
        validation_status="ACCEPTED",
    ).order_by("-published_at", "-id")[:limit]
    changed = 0
    for article in articles:
        previous = article.validation_status
        validation = revalidate_article(article, persist=True, client=client)
        if validation["status"] != previous:
            changed += 1
    return changed


def record_endpoint_success(endpoint) -> None:
    endpoint.last_success_at = dj_timezone.now()
    endpoint.consecutive_errors = 0
    endpoint.save(update_fields=["last_success_at", "consecutive_errors"])


def record_endpoint_failure(endpoint, exc, *, client=None, log=None) -> None:
    from django.conf import settings
    from newsclip.models import FetchLog, SourceEndpoint

    endpoint.last_error_at = dj_timezone.now()
    endpoint.consecutive_errors += 1
    update_fields = ["last_error_at", "consecutive_errors"]
    disable_after = getattr(settings, "SOURCE_ENDPOINT_DISABLE_AFTER_ERRORS", 0)
    should_disable = bool(disable_after and endpoint.consecutive_errors >= int(disable_after))
    if should_disable:
        endpoint.is_active = False
        update_fields.append("is_active")
    SourceEndpoint.objects.filter(pk=endpoint.pk).update(
        last_error_at=endpoint.last_error_at,
        consecutive_errors=endpoint.consecutive_errors,
        **({"is_active": False} if should_disable else {}),
    )

    source = endpoint.source
    if endpoint.consecutive_errors >= getattr(settings, "SOURCE_ENDPOINT_DEGRADED_AFTER_ERRORS", 3):
        source.status = "DEGRADED"
        source.save(update_fields=["status"])

    message = (
        f"Endpoint com falha: {source.name} ({endpoint.endpoint_type}) "
        f"{endpoint.url} | erros seguidos: {endpoint.consecutive_errors} | {exc}"
    )
    if should_disable:
        message = f"Endpoint desativado automaticamente: {message}"
    message = sanitize_sensitive_text(message)
    if log:
        log(message, level="ERROR" if should_disable else "WARNING", client=client, source=source)
    else:
        try:
            FetchLog.objects.create(
                client=client,
                source=source,
                level="ERROR" if should_disable else "WARNING",
                message=message[:2000],
            )
        except Exception:
            pass


# —————————————————————————————————————————
# 4) Salvamento de artigos no banco
# —————————————————————————————————————————

def save_article(client, title, url, raw_date, source, content_text=None, provider="OTHER", query=""):
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
        client, processed_title, content_text or "", processed_url, processed_source, provider=provider
    )
    decision = (
        "APPROVED"
        if validation["status"] == "ACCEPTED"
        else ("REVIEW" if validation["status"] == "REVIEW" else "REJECTED")
    )
    audit_relevance_decision(
        client,
        provider=provider,
        query=query,
        title=processed_title,
        url=processed_url,
        source=processed_source,
        score=validation["score"],
        reason=validation["reason"],
        decision=decision,
    )
    if validation["status"] == "REJECTED":
        return None

    dedup_key = article_dedup_key(processed_title, processed_source)
    
    summary_text = generate_summary(content_text if content_text else processed_title)
    topic_classification = _topic_clf.classify(processed_title) # _topic_clf deve estar definido neste arquivo

    article_instance = None
    try:
        if Article.objects.filter(client=client).filter(Q(url=processed_url) | Q(dedup_key=dedup_key)).exists():
            return None

        if is_duplicate_article(client, processed_title, processed_source, processed_url):
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


