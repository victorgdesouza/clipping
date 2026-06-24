"""Coletores externos adicionais com baixo acoplamento ao comando principal."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlparse

import feedparser
import requests
from django.conf import settings
from django.utils import timezone

from newsclip.models import DiscoveryRun
from newsclip.utils import save_article


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _finish_run(run, *, status, queries=0, results=0, articles=0, error=""):
    run.status = status
    run.queries_count = queries
    run.results_count = results
    run.relevant_count = articles
    run.articles_count = articles
    run.error_message = error[:2000]
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "status", "queries_count", "results_count", "relevant_count",
            "articles_count", "error_message", "finished_at",
        ]
    )


def _youtube_reference(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    channel_match = re.search(r"(?:channel/)?(UC[\w-]{20,})", value)
    if channel_match:
        return channel_match.group(1), ""
    handle_match = re.search(r"(?:youtube\.com/)?@([\w.-]+)", value)
    if handle_match:
        return "", handle_match.group(1)
    return "", value.lstrip("@") if value else ""


def _resolve_youtube_channel(api_key: str, reference: str) -> str:
    channel_id, handle = _youtube_reference(reference)
    if channel_id or not handle or not api_key:
        return channel_id
    response = requests.get(
        YOUTUBE_CHANNELS_URL,
        params={"part": "id", "forHandle": handle, "key": api_key},
        timeout=20,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    return items[0].get("id", "") if items else ""


def fetch_youtube(client, keywords: list[str], since_dt, log=None) -> int:
    api_key = getattr(settings, "YOUTUBE_API_KEY", "")
    run = DiscoveryRun.objects.create(client=client, provider="YOUTUBE", status="RUNNING")
    saved_count = 0
    results_count = 0
    queries_count = 0
    errors = []

    try:
        channel_id = _resolve_youtube_channel(api_key, getattr(client, "youtube", ""))
        # Feeds de canal não consomem cota e são preferidos quando há channel_id.
        if channel_id:
            queries_count += 1
            response = requests.get(
                YOUTUBE_FEED_URL,
                params={"channel_id": channel_id},
                timeout=20,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            for entry in feed.entries:
                results_count += 1
                saved = save_article(
                    client=client,
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    raw_date=entry.get("published"),
                    source=f"YouTube - {entry.get('author', 'Canal monitorado')}",
                    content_text=entry.get("summary", ""),
                    provider="YOUTUBE",
                )
                saved_count += int(saved is not None)
        if api_key:
            terms = [client.name, *keywords]
            max_queries = max(1, getattr(settings, "YOUTUBE_MAX_QUERIES", 2))
            published_after = since_dt.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
            for term in list(dict.fromkeys(item.strip() for item in terms if item.strip()))[:max_queries]:
                queries_count += 1
                response = requests.get(
                    YOUTUBE_SEARCH_URL,
                    params={
                        "part": "snippet", "type": "video", "order": "date",
                        "maxResults": 25, "publishedAfter": published_after,
                        "relevanceLanguage": "pt", "regionCode": "BR",
                        "safeSearch": "moderate", "q": term, "key": api_key,
                    },
                    timeout=25,
                )
                response.raise_for_status()
                for item in response.json().get("items", []):
                    video_id = item.get("id", {}).get("videoId")
                    snippet = item.get("snippet", {})
                    if not video_id:
                        continue
                    results_count += 1
                    saved = save_article(
                        client=client,
                        title=snippet.get("title", ""),
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        raw_date=snippet.get("publishedAt"),
                        source=f"YouTube - {snippet.get('channelTitle', 'Canal')}",
                        content_text=snippet.get("description", ""),
                        provider="YOUTUBE",
                    )
                    saved_count += int(saved is not None)
        elif not channel_id:
            errors.append("Configure YOUTUBE_API_KEY ou informe um channel ID iniciado por UC")
    except requests.RequestException as exc:
        errors.append(str(exc))
        if log:
            log(f"YouTube: {exc}", level="WARNING", client=client)

    status = "PARTIAL" if errors and results_count else ("ERROR" if errors else "SUCCESS")
    _finish_run(
        run, status=status, queries=queries_count, results=results_count,
        articles=saved_count, error=" | ".join(errors),
    )
    return saved_count


def _gdelt_date(value: str):
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=dt_timezone.utc)
        except ValueError:
            continue
    return value


def fetch_gdelt(client, keywords: list[str], since_dt, log=None) -> int:
    run = DiscoveryRun.objects.create(client=client, provider="GDELT", status="RUNNING")
    saved_count = 0
    results_count = 0
    queries_count = 0
    errors = []
    terms = [client.name, *keywords]
    max_queries = max(1, getattr(settings, "GDELT_MAX_QUERIES", 3))

    try:
        selected_terms = list(dict.fromkeys(item.strip() for item in terms if item.strip()))[:max_queries]
        for index, term in enumerate(selected_terms):
            if index:
                time.sleep(getattr(settings, "GDELT_MIN_INTERVAL_SECONDS", 6))
            queries_count += 1
            response = requests.get(
                GDELT_DOC_URL,
                params={
                    "query": f'"{term}" sourcelang:portuguese',
                    "mode": "ArtList",
                    "maxrecords": getattr(settings, "GDELT_MAX_RECORDS", 75),
                    "format": "json",
                    "sort": "DateDesc",
                    "startdatetime": since_dt.astimezone(dt_timezone.utc).strftime("%Y%m%d%H%M%S"),
                },
                headers={"User-Agent": "ClippingApp/1.0"},
                timeout=30,
            )
            response.raise_for_status()
            for item in response.json().get("articles", []):
                url = item.get("url", "")
                title = item.get("title", "")
                if not url or not title:
                    continue
                results_count += 1
                domain = item.get("domain") or (urlparse(url).hostname or "GDELT")
                saved = save_article(
                    client=client,
                    title=title,
                    url=url,
                    raw_date=_gdelt_date(item.get("seendate", "")),
                    source=domain,
                    content_text=item.get("description", ""),
                    provider="GDELT",
                )
                saved_count += int(saved is not None)
    except (requests.RequestException, ValueError) as exc:
        errors.append(str(exc))
        if log:
            log(f"GDELT: {exc}", level="WARNING", client=client)

    status = "PARTIAL" if errors and results_count else ("ERROR" if errors else "SUCCESS")
    _finish_run(
        run, status=status, queries=queries_count, results=results_count,
        articles=saved_count, error=" | ".join(errors),
    )
    return saved_count
