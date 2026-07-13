from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import TranscriptExtraction


class TranscriptViewsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser("admin-transcript", "admin@example.com", "senha-segura")
        self.user = user_model.objects.create_user("usuario-transcript", "user@example.com", "senha-segura")

    def test_only_admin_can_open_extractor(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("youtube_transcript_extractor"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("youtube_transcript_extractor"))
        self.assertContains(response, "Extrator de transcrições do YouTube")

    @patch("newsclip.views.async_task", return_value="task-123")
    def test_admin_starts_valid_job(self, async_task):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("youtube_transcript_start"),
            {"url": "https://www.youtube.com/watch?v=z7EPTRsr5Qs"},
        )
        self.assertEqual(response.status_code, 202)
        job = TranscriptExtraction.objects.get()
        self.assertEqual(job.created_by, self.admin)
        self.assertEqual(job.task_id, "task-123")
        async_task.assert_called_once()
