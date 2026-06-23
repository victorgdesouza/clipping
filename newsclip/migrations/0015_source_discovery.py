from urllib.parse import urlsplit

from django.db import migrations, models
import django.db.models.deletion


def backfill_source_metadata(apps, schema_editor):
    Source = apps.get_model("newsclip", "Source")
    for source in Source.objects.all().iterator():
        host = (urlsplit(source.url or "").hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        source.domain = host
        source.status = "ACTIVE" if source.is_active else "CANDIDATE"
        source.save(update_fields=["domain", "status"])


class Migration(migrations.Migration):

    dependencies = [
        ("newsclip", "0014_article_url_per_client"),
    ]

    operations = [
        migrations.AddField(
            model_name="source",
            name="confidence_score",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Confianca"),
        ),
        migrations.AddField(
            model_name="source",
            name="discovered_automatically",
            field=models.BooleanField(default=False, verbose_name="Descoberta automaticamente?"),
        ),
        migrations.AddField(
            model_name="source",
            name="discovery_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Vezes descoberta"),
        ),
        migrations.AddField(
            model_name="source",
            name="discovery_provider",
            field=models.CharField(blank=True, max_length=50, verbose_name="Provedor de descoberta"),
        ),
        migrations.AddField(
            model_name="source",
            name="domain",
            field=models.CharField(blank=True, db_index=True, max_length=255, verbose_name="Dominio"),
        ),
        migrations.AddField(
            model_name="source",
            name="first_discovered_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Primeira descoberta"),
        ),
        migrations.AddField(
            model_name="source",
            name="last_discovered_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Ultima descoberta"),
        ),
        migrations.AddField(
            model_name="source",
            name="status",
            field=models.CharField(
                choices=[
                    ("CANDIDATE", "Candidata"),
                    ("VERIFIED", "Verificada"),
                    ("ACTIVE", "Ativa"),
                    ("DEGRADED", "Com falhas"),
                    ("BLOCKED", "Bloqueada"),
                    ("DISCARDED", "Descartada"),
                ],
                db_index=True,
                default="ACTIVE",
                max_length=20,
                verbose_name="Status",
            ),
        ),
        migrations.AlterField(
            model_name="source",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("RSS", "RSS Feed"),
                    ("SCRAPE", "Web Scrape"),
                    ("API", "API (NewsAPI/NewsData)"),
                    ("DISCOVERED", "Descoberta automatica"),
                    ("SITEMAP", "Sitemap"),
                    ("NEWS_SITEMAP", "Google News Sitemap"),
                    ("YOUTUBE", "Canal do YouTube"),
                ],
                default="RSS",
                max_length=20,
                verbose_name="Tipo",
            ),
        ),
        migrations.CreateModel(
            name="SourceEndpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endpoint_type", models.CharField(choices=[("RSS", "RSS/Atom"), ("SITEMAP", "Sitemap"), ("NEWS_SITEMAP", "Google News Sitemap"), ("YOUTUBE", "YouTube"), ("WEB", "Pagina web")], db_index=True, max_length=20)),
                ("url", models.URLField(max_length=1000)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_errors", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="endpoints", to="newsclip.source")),
            ],
        ),
        migrations.CreateModel(
            name="DiscoveryResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(db_index=True, max_length=50)),
                ("query", models.TextField()),
                ("title", models.CharField(max_length=500)),
                ("url", models.URLField(max_length=2000)),
                ("description", models.TextField(blank=True)),
                ("relevance_score", models.PositiveSmallIntegerField(default=0)),
                ("is_relevant", models.BooleanField(db_index=True, default=False)),
                ("discovered_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="discovery_results", to="newsclip.client")),
                ("source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="discovery_results", to="newsclip.source")),
            ],
        ),
        migrations.RunPython(backfill_source_metadata, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="sourceendpoint",
            constraint=models.UniqueConstraint(fields=("source", "url"), name="unique_endpoint_url_per_source"),
        ),
        migrations.AddIndex(
            model_name="discoveryresult",
            index=models.Index(fields=["client", "provider", "-discovered_at"], name="newsclip_di_client__bfb60a_idx"),
        ),
    ]
