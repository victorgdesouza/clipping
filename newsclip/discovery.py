"""Descoberta automatica de noticias e fontes na web aberta."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from newsclip.models import Article, DiscoveryResult, DiscoveryRun, Source, SourceEndpoint
from newsclip.utils import (
    build_client_search_queries,
    audit_relevance_decision,
    client_positive_terms,
    contains_excluded_term,
    save_article,
    validate_article_candidate,
)


USER_AGENT = "ClippingDiscovery/1.0 (+monitoramento de imprensa)"
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}


def normalize_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value or "")
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    host = parts.hostname.casefold()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    query = urlencode(
        sorted((key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.casefold() not in TRACKING_QUERY_KEYS)
    )
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), f"{host}{port}", path, query, ""))


def domain_from_url(value: str) -> str:
    host = (urlsplit(value or "").hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def origin_from_url(value: str) -> str:
    parts = urlsplit(value)
    return f"{parts.scheme}://{parts.netloc}/"


def is_public_http_url(value: str) -> bool:
    parts = urlsplit(value or "")
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if parts.username or parts.password:
        return False
    host = parts.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            return False
    return bool(addresses)


def build_discovery_queries(client, keywords: list[str], max_queries: int = 12) -> list[str]:
    return build_client_search_queries(client, max_queries=max_queries)


def relevance_score(title: str, description: str, terms: list[str]) -> int:
    title_norm = normalize_text(title)
    description_norm = normalize_text(description)
    score = 0
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term:
            continue
        if normalized_term in title_norm:
            score += 70
        elif normalized_term in description_norm:
            score += 35
    return min(score, 100)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    description: str = ""
    published_at: str | None = None


class BraveSearchProvider:
    name = "BRAVE"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: int = 20, count: int = 20, freshness: str = "pm"):
        self.api_key = api_key
        self.timeout = timeout
        self.count = max(1, min(count, 20))
        self.freshness = freshness

    def search(self, query: str) -> list[SearchResult]:
        response = requests.get(
            self.endpoint,
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            params={
                "q": query,
                "count": self.count,
                "country": "br",
                "search_lang": "pt-br",
                "freshness": self.freshness,
                "safesearch": "moderate",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = [
            *(payload.get("web", {}).get("results", []) or []),
            *(payload.get("news", {}).get("results", []) or []),
        ]
        seen = set()
        results = []
        for item in raw_results:
            url = canonicalize_url(item.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    description=(item.get("description") or item.get("snippet") or "").strip(),
                    published_at=item.get("page_age") or item.get("age"),
                )
            )
        return results


def _source_for_result(result: SearchResult, provider: str) -> tuple[Source, bool]:
    domain = domain_from_url(result.url)
    now = timezone.now()
    source = Source.objects.filter(domain=domain).order_by("id").first()
    if source is None:
        source = Source.objects.filter(url__icontains=domain).order_by("id").first()
    created = source is None
    if created:
        source = Source.objects.create(
            name=domain,
            domain=domain,
            url=origin_from_url(result.url),
            source_type="DISCOVERED",
            is_active=False,
            status="CANDIDATE",
            discovered_automatically=True,
            discovery_provider=provider,
            confidence_score=10,
            discovery_count=1,
            first_discovered_at=now,
            last_discovered_at=now,
        )
    else:
        updates = {
            "domain": source.domain or domain,
            "last_discovered_at": now,
            "discovery_count": source.discovery_count + 1,
            "confidence_score": min(100, source.confidence_score + 10),
        }
        Source.objects.filter(pk=source.pk).update(**updates)
        for field, value in updates.items():
            setattr(source, field, value)
    return source, created


def discover_client_sources(client, keywords: list[str], log=None, force: bool = False) -> dict[str, int]:
    stats = {
        "queries": 0,
        "results": 0,
        "relevant": 0,
        "articles": 0,
        "new_sources": 0,
        "profiled": 0,
        "skipped": 0,
    }
    api_key = getattr(settings, "BRAVE_SEARCH_API_KEY", "")
    if not api_key:
        return stats

    minimum_interval = timedelta(hours=getattr(settings, "DISCOVERY_MIN_INTERVAL_HOURS", 24))
    latest_run = (
        DiscoveryRun.objects.filter(
            client=client,
            provider="BRAVE",
            status__in=["SUCCESS", "PARTIAL"],
        )
        .order_by("-started_at")
        .first()
    )
    if not force and latest_run and timezone.now() - latest_run.started_at < minimum_interval:
        stats["skipped"] = 1
        return stats

    run = DiscoveryRun.objects.create(client=client, provider="BRAVE", status="RUNNING")

    provider = BraveSearchProvider(
        api_key=api_key,
        timeout=getattr(settings, "BRAVE_SEARCH_TIMEOUT_SECONDS", 10),
        count=getattr(settings, "BRAVE_SEARCH_RESULTS_PER_QUERY", 20),
        freshness=getattr(settings, "BRAVE_SEARCH_FRESHNESS", "pm"),
    )
    queries = build_discovery_queries(
        client,
        keywords,
        max_queries=getattr(settings, "BRAVE_SEARCH_MAX_QUERIES", 12),
    )
    terms = client_positive_terms(client)
    sources_to_profile = []
    errors = []

    search_results = []
    search_workers = max(1, min(getattr(settings, "BRAVE_SEARCH_WORKERS", 4), len(queries) or 1))
    with ThreadPoolExecutor(max_workers=search_workers) as executor:
        futures = {executor.submit(provider.search, query): query for query in queries}
        for future in as_completed(futures):
            query = futures[future]
            try:
                search_results.append((query, future.result()))
                stats["queries"] += 1
            except requests.RequestException as exc:
                errors.append(str(exc))
                if log:
                    log(f"Brave falhou para '{query}': {exc}", level="WARNING", client=client)

    for query, results in search_results:
        for result in results:
            stats["results"] += 1
            validation = validate_article_candidate(
                client,
                result.title,
                result.description,
                result.url,
                domain_from_url(result.url),
                provider=provider.name,
            )
            score = validation["score"]
            relevant = validation["status"] == "ACCEPTED"
            audit_relevance_decision(
                client,
                provider=provider.name,
                query=query,
                title=result.title,
                url=result.url,
                source=domain_from_url(result.url),
                score=score,
                reason=validation["reason"],
                decision="APPROVED" if relevant else ("REVIEW" if validation["status"] == "REVIEW" else "REJECTED"),
            )
            source = None
            source_created = False
            if relevant:
                source, source_created = _source_for_result(result, provider.name)
                if source_created:
                    stats["new_sources"] += 1
                    sources_to_profile.append(source)
                stats["relevant"] += 1

            DiscoveryResult.objects.update_or_create(
                client=client,
                provider=provider.name,
                url=result.url,
                defaults={
                    "source": source,
                    "query": query,
                    "title": result.title[:500],
                    "description": result.description,
                    "relevance_score": score,
                    "is_relevant": relevant,
                },
            )
            if relevant:
                saved = save_article(
                    client=client,
                    title=result.title,
                    url=result.url,
                    raw_date=result.published_at,
                    source=source.name if source else domain_from_url(result.url),
                    content_text=result.description,
                    provider="BRAVE",
                    query=query,
                )
                stats["articles"] += int(saved is not None)

    profile_limit = getattr(settings, "DISCOVERY_PROFILE_NEW_SOURCES", 5)
    sources_to_profile = sources_to_profile[:profile_limit]
    profile_workers = max(1, min(3, len(sources_to_profile) or 1))
    with ThreadPoolExecutor(max_workers=profile_workers) as executor:
        futures = {executor.submit(profile_source, source): source for source in sources_to_profile}
        for future in as_completed(futures):
            source = futures[future]
            try:
                if future.result():
                    stats["profiled"] += 1
            except requests.RequestException as exc:
                errors.append(str(exc))
                if log:
                    log(f"Nao foi possivel perfilar {source.domain}: {exc}", level="WARNING", client=client, source=source)

    run.status = "PARTIAL" if errors and stats["queries"] else ("ERROR" if errors else "SUCCESS")
    run.queries_count = stats["queries"]
    run.results_count = stats["results"]
    run.relevant_count = stats["relevant"]
    run.articles_count = stats["articles"]
    run.new_sources_count = stats["new_sources"]
    run.error_message = " | ".join(errors[:5])
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "status",
            "queries_count",
            "results_count",
            "relevant_count",
            "articles_count",
            "new_sources_count",
            "error_message",
            "finished_at",
        ]
    )
    return stats


def _endpoint_type(url: str, content_type: str = "") -> str:
    normalized = normalize_text(url)
    if "news-sitemap" in normalized or "sitemap-news" in normalized:
        return "NEWS_SITEMAP"
    if "sitemap" in normalized or "xml" in content_type.casefold():
        return "SITEMAP"
    return "RSS"


def profile_source(source: Source) -> int:
    if not is_public_http_url(source.url):
        return 0
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"}
    homepage = requests.get(source.url, headers=headers, timeout=15, allow_redirects=True)
    homepage.raise_for_status()
    final_origin = origin_from_url(homepage.url)
    candidates = set()

    soup = BeautifulSoup(homepage.text, "html.parser")
    for link in soup.select('link[rel="alternate"][href]'):
        content_type = (link.get("type") or "").casefold()
        if "rss" in content_type or "atom" in content_type:
            candidates.add(("RSS", urljoin(homepage.url, link.get("href"))))

    try:
        robots = requests.get(urljoin(final_origin, "robots.txt"), headers=headers, timeout=10)
        if robots.ok:
            for match in re.findall(r"(?im)^\s*Sitemap:\s*(\S+)\s*$", robots.text):
                candidates.add((_endpoint_type(match, "application/xml"), match.strip()))
    except requests.RequestException:
        pass

    page_lower = homepage.text.casefold()
    if "wp-content" in page_lower or "wordpress" in page_lower or "/wp-json/" in page_lower:
        candidates.add(("RSS", urljoin(final_origin, "feed/")))
        candidates.add(("SITEMAP", urljoin(final_origin, "wp-sitemap.xml")))

    created = 0
    with transaction.atomic():
        for endpoint_type, url in candidates:
            canonical = canonicalize_url(url)
            if not canonical:
                continue
            _, was_created = SourceEndpoint.objects.get_or_create(
                source=source,
                url=canonical,
                defaults={"endpoint_type": endpoint_type, "is_active": True},
            )
            created += int(was_created)
        if candidates:
            source.status = "VERIFIED"
            source.confidence_score = max(source.confidence_score, 50)
            source.save(update_fields=["status", "confidence_score"])
    return created


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def parse_sitemap(xml_text: str) -> tuple[list[str], list[dict]]:
    root = ElementTree.fromstring(xml_text)
    child_sitemaps = []
    articles = []
    if _xml_local_name(root.tag) == "sitemapindex":
        for node in root:
            loc = next((child.text for child in node if _xml_local_name(child.tag) == "loc"), None)
            if loc:
                child_sitemaps.append(loc.strip())
        return child_sitemaps, articles

    for node in root:
        values = {}
        for descendant in node.iter():
            name = _xml_local_name(descendant.tag)
            if descendant.text and name in {"loc", "lastmod", "title", "publication_date"}:
                values[name] = descendant.text.strip()
        if values.get("loc"):
            articles.append(values)
    return child_sitemaps, articles


def extract_article_page(url: str) -> dict[str, str]:
    if not is_public_http_url(url):
        return {}
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = ""
    description = ""
    published_at = ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "null")
        except (TypeError, json.JSONDecodeError):
            continue
        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("@type") in {"NewsArticle", "Article", "ReportageNewsArticle"}:
                title = title or str(record.get("headline") or "")
                description = description or str(record.get("description") or record.get("articleBody") or "")
                published_at = published_at or str(record.get("datePublished") or "")
    title = title or (soup.select_one('meta[property="og:title"]') or {}).get("content", "")
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else "")
    description = description or (soup.select_one('meta[property="og:description"]') or {}).get("content", "")
    description = description or (soup.select_one('meta[name="description"]') or {}).get("content", "")
    if not description:
        article = soup.select_one("article")
        description = article.get_text(" ", strip=True)[:8000] if article else ""
    return {"title": title.strip(), "description": description.strip(), "published_at": published_at}


def fetch_sitemap_endpoint(command, client, endpoint: SourceEndpoint, keywords: list[str], since_dt) -> int:
    if not is_public_http_url(endpoint.url):
        return 0
    headers = {"User-Agent": USER_AGENT}
    max_children = getattr(settings, "SITEMAP_MAX_CHILDREN", 3)
    max_articles = getattr(settings, "SITEMAP_MAX_ARTICLES", 30)
    saved_count = 0
    try:
        response = requests.get(endpoint.url, headers=headers, timeout=20)
        response.raise_for_status()
        children, articles = parse_sitemap(response.text)
        selected_children = children if len(children) <= 20 else children[:max_children]
        for child_url in selected_children:
            if not is_public_http_url(child_url):
                continue
            child_response = requests.get(child_url, headers=headers, timeout=20)
            child_response.raise_for_status()
            _, child_articles = parse_sitemap(child_response.text)
            articles.extend(child_articles)

        articles.sort(
            key=lambda item: item.get("publication_date") or item.get("lastmod") or "",
            reverse=True,
        )
        for item in articles[:max_articles]:
            raw_date = item.get("publication_date") or item.get("lastmod")
            if raw_date:
                try:
                    parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    if timezone.is_naive(parsed):
                        parsed = timezone.make_aware(parsed)
                    if parsed < since_dt:
                        continue
                except ValueError:
                    pass
            title = item.get("title", "")
            description = ""
            if not title or not relevance_score(title, "", keywords):
                page = extract_article_page(item["loc"])
                title = title or page.get("title", "")
                description = page.get("description", "")
                raw_date = raw_date or page.get("published_at")
            validation = validate_article_candidate(
                client,
                title,
                description,
                canonicalize_url(item["loc"]),
                endpoint.source.name,
                provider="SITEMAP",
            )
            if validation["status"] != "ACCEPTED":
                continue
            saved = save_article(
                client=client,
                title=title,
                url=canonicalize_url(item["loc"]),
                raw_date=raw_date,
                source=endpoint.source.name,
                content_text=description,
                provider="SITEMAP",
                query=endpoint.url,
            )
            saved_count += int(saved is not None)

        endpoint.last_success_at = timezone.now()
        endpoint.consecutive_errors = 0
        endpoint.save(update_fields=["last_success_at", "consecutive_errors"])
        return saved_count
    except (requests.RequestException, ElementTree.ParseError) as exc:
        endpoint.last_error_at = timezone.now()
        endpoint.consecutive_errors += 1
        endpoint.save(update_fields=["last_error_at", "consecutive_errors"])
        command.log(
            f"Erro no sitemap {endpoint.source.name}: {exc}",
            level="ERROR",
            client=client,
            source=endpoint.source,
        )
        return 0
