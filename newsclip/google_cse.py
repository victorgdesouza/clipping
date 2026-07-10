"""Coletor da Google Custom Search JSON API."""

from __future__ import annotations

from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from newsclip.models import DiscoveryRun
from newsclip.utils import (
    client_context_terms,
    client_excluded_terms,
    client_identity_terms,
    normalize_match_text,
    sanitize_sensitive_text,
    save_article,
    strong_client_identity_terms,
)


GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _quoted_search_term(value: str) -> str:
    clean = " ".join((value or "").replace('"', " ").split())
    return f'"{clean}"' if " " in clean else clean


def build_google_cse_queries(client, max_queries: int) -> list[str]:
    """Monta campanha curta equilibrando identidade, variação, contexto e exclusões."""
    max_queries = max(1, int(max_queries or 1))
    identities = strong_client_identity_terms(client) or client_identity_terms(client)
    contexts = client_context_terms(client)
    excluded_terms = client_excluded_terms(client)[:3]
    queries = []
    seen = set()

    def add(*terms):
        query_terms = [_quoted_search_term(term) for term in terms if (term or "").strip()]
        query_terms.extend(f"-{_quoted_search_term(term)}" for term in excluded_terms)
        query = " ".join(term for term in query_terms if term).strip()
        normalized = normalize_match_text(query)
        if query and normalized not in seen:
            queries.append(query)
            seen.add(normalized)

    if not identities:
        return []

    primary_identity = identities[0]
    add(primary_identity)

    # A busca rápida precisa cobrir ao menos o nome oficial e a principal variação.
    if len(identities) > 1:
        add(identities[1])

    # Na busca completa, a terceira consulta liga a identidade ao contexto principal.
    if contexts:
        add(primary_identity, contexts[0])

    for identity in identities[2:]:
        add(identity)
    for context in contexts[1:]:
        add(primary_identity, context)

    if len(queries) < max_queries:
        add(primary_identity, "notícias")

    return queries[:max_queries]


def _finish_run(run, *, status, queries=0, results=0, articles=0, error=""):
    run.status = status
    run.queries_count = queries
    run.results_count = results
    run.relevant_count = articles
    run.articles_count = articles
    run.error_message = sanitize_sensitive_text(error)[:2000]
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "status", "queries_count", "results_count", "relevant_count",
            "articles_count", "error_message", "finished_at",
        ]
    )


def _published_date(item):
    metatags = (item.get("pagemap") or {}).get("metatags") or []
    if not metatags:
        return None
    metadata = metatags[0] or {}
    for key in (
        "article:published_time", "datepublished", "date", "datecreated",
        "og:published_time",
    ):
        if metadata.get(key):
            return metadata[key]
    return None


def fetch_google_cse(client, since_dt, log=None, *, quick=False) -> int:
    run = DiscoveryRun.objects.create(client=client, provider="GOOGLE_CSE", status="RUNNING")
    api_key = getattr(settings, "GOOGLE_API_KEY", "") or ""
    cse_id = getattr(settings, "GOOGLE_CSE_ID", "") or ""
    saved_count = 0
    results_count = 0
    queries_count = 0
    errors = []

    if not getattr(settings, "GOOGLE_CSE_ENABLED", True):
        _finish_run(run, status="SUCCESS")
        return 0
    if not api_key or not cse_id:
        message = "Google CSE não configurado; informe GOOGLE_API_KEY e GOOGLE_CSE_ID."
        _finish_run(run, status="ERROR", error=message)
        return 0

    setting_name = "GOOGLE_CSE_QUICK_MAX_QUERIES" if quick else "GOOGLE_CSE_MAX_QUERIES"
    max_queries = max(1, getattr(settings, setting_name, 2 if quick else 3))
    max_results = max(1, min(10, getattr(settings, "GOOGLE_CSE_RESULTS_PER_QUERY", 10)))
    timeout = max(5, getattr(settings, "GOOGLE_CSE_REQUEST_TIMEOUT", 20))
    selected_terms = build_google_cse_queries(client, max_queries=max_queries)
    lookback_days = max(1, min(365, (timezone.now() - since_dt).days + 1))

    try:
        for term in selected_terms:
            queries_count += 1
            response = requests.get(
                GOOGLE_CSE_URL,
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": term,
                    "num": max_results,
                    "lr": "lang_pt",
                    "gl": "br",
                    "cr": "countryBR",
                    "dateRestrict": f"d{lookback_days}",
                    "safe": "active",
                },
                timeout=timeout,
            )
            if response.status_code in {403, 429}:
                message = "Google CSE atingiu o limite de cota ou recusou a consulta; demais fontes continuarão normalmente."
                errors.append(message)
                if log:
                    log(message, level="WARNING", client=client)
                break

            response.raise_for_status()
            for item in response.json().get("items", []):
                url = item.get("link", "")
                title = item.get("title", "")
                if not url or not title:
                    continue
                results_count += 1
                source = item.get("displayLink") or urlparse(url).hostname or "Google CSE"
                saved = save_article(
                    client=client,
                    title=title,
                    url=url,
                    raw_date=_published_date(item),
                    source=source,
                    content_text=item.get("snippet", ""),
                    provider="GOOGLE_CSE",
                    query=term,
                )
                saved_count += int(saved is not None)
    except (requests.RequestException, ValueError) as exc:
        message = sanitize_sensitive_text(str(exc))
        errors.append(message)
        if log:
            log(f"Google CSE indisponível nesta tentativa: {message}", level="WARNING", client=client)

    status = "PARTIAL" if errors and results_count else ("ERROR" if errors else "SUCCESS")
    _finish_run(
        run,
        status=status,
        queries=queries_count,
        results=results_count,
        articles=saved_count,
        error=" | ".join(errors),
    )
    return saved_count
