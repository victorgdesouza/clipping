import hashlib
import re
import unicodedata

from django.db import migrations, models


def normalize(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def fingerprint(title, source):
    normalized_source = normalize(source)
    normalized_title = normalize(title)
    for separator in (" - ", " | ", " — ", " – "):
        suffix = f"{separator}{normalized_source}"
        if normalized_source and normalized_title.endswith(suffix):
            normalized_title = normalized_title[: -len(suffix)].strip()
            break
    normalized_title = re.sub(r"[^a-z0-9]+", " ", normalized_title).strip()
    return hashlib.sha256(f"{normalized_source}|{normalized_title}".encode("utf-8")).hexdigest()


def backfill_dedup_and_exclusions(apps, schema_editor):
    Client = apps.get_model("newsclip", "Client")
    Article = apps.get_model("newsclip", "Article")

    for client in Client.objects.all().iterator():
        client_context = normalize(f"{client.name} {client.keywords}")
        excluded_terms = [term.strip() for term in (client.excluded_keywords or "").split(",") if term.strip()]
        if (
            "rio preto" in client_context
            and "rio preto da eva" not in client_context
            and not any(
                normalize(term) == "rio preto da eva" for term in excluded_terms
            )
        ):
            excluded_terms.append("Rio Preto da Eva")
            client.excluded_keywords = ", ".join(excluded_terms)
            client.save(update_fields=["excluded_keywords"])

        normalized_exclusions = [normalize(term) for term in excluded_terms]
        seen = set()
        for article in Article.objects.filter(client=client).order_by("id").iterator():
            base_key = fingerprint(article.title, article.source)
            is_duplicate = base_key in seen
            article.dedup_key = f"{base_key}:{article.pk}" if is_duplicate else base_key
            seen.add(base_key)

            searchable = normalize(f"{article.title} {article.summary or ''} {article.content or ''}")
            has_excluded_term = any(term and term in searchable for term in normalized_exclusions)
            if is_duplicate or has_excluded_term:
                article.excluded = True
                article.save(update_fields=["dedup_key", "excluded"])
            else:
                article.save(update_fields=["dedup_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("newsclip", "0016_discoveryrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="excluded_keywords",
            field=models.TextField(
                blank=True,
                help_text="Separe por virgulas. Noticias que contenham estes termos nao serao salvas.",
                verbose_name="Termos excluidos",
            ),
        ),
        migrations.AddField(
            model_name="article",
            name="dedup_key",
            field=models.CharField(blank=True, db_index=True, max_length=96),
        ),
        migrations.RunPython(backfill_dedup_and_exclusions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                fields=("client", "dedup_key"),
                name="unique_article_dedup_per_client",
            ),
        ),
    ]
