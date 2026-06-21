from django.db import migrations, models


def backfill_postgres_search_vectors(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("newsclip_article")
    schema_editor.execute(
        f"""
        UPDATE {table}
        SET search_vector =
            setweight(to_tsvector('portuguese', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('portuguese', coalesce(summary, '')), 'B') ||
            setweight(to_tsvector('portuguese', coalesce(content, '')), 'C') ||
            setweight(to_tsvector('portuguese', coalesce(source, '')), 'D')
        """
    )


class Migration(migrations.Migration):

    dependencies = [
        ("newsclip", "0013_generatedreport"),
    ]

    operations = [
        migrations.AlterField(
            model_name="article",
            name="url",
            field=models.TextField(verbose_name="Link"),
        ),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                fields=("client", "url"),
                name="unique_article_url_per_client",
            ),
        ),
        migrations.RunPython(backfill_postgres_search_vectors, migrations.RunPython.noop),
    ]
