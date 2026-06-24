from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("newsclip", "0017_article_dedup_and_exclusions"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="provider",
            field=models.CharField(db_index=True, default="OTHER", max_length=32),
        ),
        migrations.AddField(
            model_name="article",
            name="relevance_score",
            field=models.PositiveSmallIntegerField(db_index=True, default=0),
        ),
        migrations.AddField(
            model_name="article",
            name="validation_status",
            field=models.CharField(
                choices=[("ACCEPTED", "Validada"), ("REVIEW", "Revisar"), ("REJECTED", "Rejeitada")],
                db_index=True,
                default="ACCEPTED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="article",
            name="validation_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
