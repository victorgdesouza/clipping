from types import SimpleNamespace

from django.test import SimpleTestCase

from .transcripts import export_files, extract_video_id, format_clock


class TranscriptHelpersTests(SimpleTestCase):
    def test_accepts_common_youtube_urls(self):
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=z7EPTRsr5Qs"), "z7EPTRsr5Qs")
        self.assertEqual(extract_video_id("https://youtu.be/z7EPTRsr5Qs?t=20"), "z7EPTRsr5Qs")
        self.assertEqual(extract_video_id("https://www.youtube.com/shorts/z7EPTRsr5Qs"), "z7EPTRsr5Qs")

    def test_rejects_non_youtube_url(self):
        with self.assertRaises(ValueError):
            extract_video_id("https://example.com/watch?v=z7EPTRsr5Qs")

    def test_exports_text_json_and_srt(self):
        job = SimpleNamespace(
            video_id="z7EPTRsr5Qs", video_url="https://www.youtube.com/watch?v=z7EPTRsr5Qs",
            title="Título seguro", channel="Canal", language="pt", source="api",
            segments=[{"timestamp": "00:01", "text": "Olá", "start": 1, "end": 2}],
        )
        files = export_files(job)
        self.assertIn("transcricao_z7EPTRsr5Qs.txt", files)
        self.assertIn("[00:01] Olá", files["transcricao_z7EPTRsr5Qs.txt"].decode("utf-8"))
        self.assertIn(b"00:00:01,000 --> 00:00:02,000", files["transcricao_z7EPTRsr5Qs.srt"])
        self.assertEqual(format_clock(61.2), "01:01")
