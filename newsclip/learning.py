"""Aprendizado explicável baseado nas decisões manuais de validação."""

from __future__ import annotations

import math
import re
import time
from collections import Counter

from django.conf import settings

from newsclip.utils import normalize_match_text


PROFILE_CACHE = {}
LEARNING_STOP_WORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "entre", "na", "nas", "no", "nos", "o", "os", "para", "por",
    "que", "se", "sem", "um", "uma",
}


def invalidate_client_learning_profile(client_id):
    PROFILE_CACHE.pop(int(client_id), None)


def _words(value):
    normalized = normalize_match_text(value)
    return [
        word
        for word in re.findall(r"[a-z0-9]{3,}", normalized)
        if word not in LEARNING_STOP_WORDS
    ]


def extract_learning_features(title="", content="", source="", provider=""):
    features = set()
    title_words = _words(title)[:40]
    content_words = _words(content)[:120]

    features.update(f"title:{word}" for word in title_words)
    features.update(f"text:{word}" for word in content_words)
    features.update(
        f"title_pair:{first}_{second}"
        for first, second in zip(title_words, title_words[1:])
    )

    normalized_source = normalize_match_text(source)
    normalized_provider = normalize_match_text(provider)
    if normalized_source:
        features.add(f"source:{normalized_source}")
    if normalized_provider:
        features.add(f"provider:{normalized_provider}")
    return features


def record_manual_feedback(articles, decision, user=None):
    from newsclip.models import ValidationFeedback

    if decision not in {"ACCEPTED", "REVIEW", "REJECTED"}:
        return 0

    saved = 0
    client_ids = set()
    for article in articles:
        try:
            content = (article.content or article.summary or "")[:4000]
            ValidationFeedback.objects.update_or_create(
                article=article,
                defaults={
                    "client": article.client,
                    "decided_by": user if getattr(user, "is_authenticated", False) else None,
                    "decision": decision,
                    "base_status": article.validation_status,
                    "base_score": max(0, min(int(article.relevance_score or 0), 100)),
                    "base_reason": (article.validation_reason or "")[:255],
                    "title": (article.title or "")[:500],
                    "content": content,
                    "source": (article.source or "")[:255],
                    "provider": (article.provider or "")[:32],
                },
            )
            saved += 1
            client_ids.add(article.client_id)
        except Exception:
            # O aprendizado nunca pode impedir a decisão manual do usuário.
            continue

    for client_id in client_ids:
        invalidate_client_learning_profile(client_id)
    return saved


def _build_learning_profile(client_id):
    from newsclip.models import ValidationFeedback

    max_feedback = max(10, getattr(settings, "VALIDATION_LEARNING_MAX_FEEDBACK", 500))
    feedback_items = list(
        ValidationFeedback.objects.filter(
            client_id=client_id,
            decision__in=["ACCEPTED", "REJECTED"],
        ).order_by("-updated_at")[:max_feedback]
    )
    accepted = [item for item in feedback_items if item.decision == "ACCEPTED"]
    rejected = [item for item in feedback_items if item.decision == "REJECTED"]
    min_accepted = max(1, getattr(settings, "VALIDATION_LEARNING_MIN_ACCEPTED", 3))
    min_rejected = max(1, getattr(settings, "VALIDATION_LEARNING_MIN_REJECTED", 3))

    profile = {
        "active": len(accepted) >= min_accepted and len(rejected) >= min_rejected,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "weights": {},
    }
    if not profile["active"]:
        return profile

    accepted_features = Counter()
    rejected_features = Counter()
    for item in accepted:
        accepted_features.update(
            extract_learning_features(item.title, item.content, item.source, item.provider)
        )
    for item in rejected:
        rejected_features.update(
            extract_learning_features(item.title, item.content, item.source, item.provider)
        )

    min_occurrences = max(
        2,
        getattr(settings, "VALIDATION_LEARNING_MIN_FEATURE_OCCURRENCES", 2),
    )
    weights = {}
    for feature in accepted_features.keys() | rejected_features.keys():
        accepted_count = accepted_features[feature]
        rejected_count = rejected_features[feature]
        if accepted_count + rejected_count < min_occurrences:
            continue
        accepted_rate = (accepted_count + 1) / (len(accepted) + 2)
        rejected_rate = (rejected_count + 1) / (len(rejected) + 2)
        weights[feature] = math.log(accepted_rate / rejected_rate)
    profile["weights"] = weights
    return profile


def get_client_learning_profile(client):
    if not getattr(settings, "VALIDATION_LEARNING_ENABLED", True) or not getattr(client, "pk", None):
        return {"active": False, "accepted": 0, "rejected": 0, "weights": {}}

    client_id = int(client.pk)
    now = time.monotonic()
    cache_seconds = max(0, getattr(settings, "VALIDATION_LEARNING_CACHE_SECONDS", 300))
    cached = PROFILE_CACHE.get(client_id)
    if cached and cached[0] > now:
        return cached[1]

    profile = _build_learning_profile(client_id)
    PROFILE_CACHE[client_id] = (now + cache_seconds, profile)
    return profile


def _feature_label(feature):
    category, _, value = feature.partition(":")
    labels = {
        "source": "fonte",
        "provider": "provedor",
        "title": "título",
        "title_pair": "expressão",
        "text": "conteúdo",
    }
    return f"{labels.get(category, category)} {value.replace('_', ' ')}"


def learned_score_adjustment(client, title="", content="", source="", provider=""):
    profile = get_client_learning_profile(client)
    if not profile["active"] or not profile["weights"]:
        return 0, ""

    features = extract_learning_features(title, content, source, provider)
    matched = [
        (feature, profile["weights"][feature])
        for feature in features
        if feature in profile["weights"]
    ]
    if not matched:
        return 0, ""

    strongest = sorted(matched, key=lambda item: abs(item[1]), reverse=True)[:5]
    raw_adjustment = sum(weight for _, weight in strongest) / len(strongest) * 6
    max_adjustment = max(1, getattr(settings, "VALIDATION_LEARNING_MAX_ADJUSTMENT", 12))
    adjustment = max(-max_adjustment, min(max_adjustment, int(round(raw_adjustment))))
    if adjustment == 0:
        return 0, ""

    signals = ", ".join(_feature_label(feature) for feature, _ in strongest[:3])
    sample_count = profile["accepted"] + profile["rejected"]
    reason = f"aprendizado manual {adjustment:+d} ({signals}; {sample_count} exemplos)"
    return adjustment, reason
