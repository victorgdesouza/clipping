import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("newsclip", "0012_alter_article_options_alter_article_content_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GeneratedReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(max_length=255)),
                (
                    "format",
                    models.CharField(choices=[("pdf", "PDF"), ("xlsx", "Excel"), ("csv", "CSV")], max_length=10),
                ),
                ("period_label", models.CharField(max_length=50)),
                ("content_type", models.CharField(max_length=100)),
                ("content", models.BinaryField()),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="generated_reports",
                        to="newsclip.client",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="generated_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="generatedreport",
            constraint=models.UniqueConstraint(
                fields=("client", "filename"),
                name="unique_report_filename_per_client",
            ),
        ),
    ]
