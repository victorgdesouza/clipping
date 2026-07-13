from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("newsclip", "0023_backfill_manual_feedback")]

    operations = [
        migrations.CreateModel(
            name="TranscriptExtraction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("status", models.CharField(choices=[("queued", "Na fila"), ("running", "Em execucao"), ("completed", "Concluida"), ("failed", "Falhou")], db_index=True, default="queued", max_length=16)),
                ("video_url", models.URLField(max_length=1000)),
                ("video_id", models.CharField(blank=True, max_length=16)),
                ("title", models.CharField(blank=True, max_length=500)),
                ("channel", models.CharField(blank=True, max_length=500)),
                ("language", models.CharField(blank=True, max_length=80)),
                ("source", models.CharField(blank=True, max_length=64)),
                ("segments", models.JSONField(blank=True, default=list)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transcript_extractions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
