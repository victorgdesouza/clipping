"""Extracao e exportacao de transcricoes, sem dependencia da interface web."""
from __future__ import annotations

import html
import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_LANGUAGES = ("pt-BR", "pt", "pt-PT", "en")


class TranscriptError(RuntimeError):
    pass


def extract_video_id(value: str) -> str:
    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().split(":")[0].removeprefix("www.").removeprefix("m.")
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
                video_id = parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Use um link legítimo de vídeo do YouTube.")
    return video_id


def format_clock(seconds: float, milliseconds: bool = False) -> str:
    total = max(0, int(round(float(seconds) * 1000)))
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}" if milliseconds else (f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text))).strip()


def _segments(items) -> list[dict]:
    result, seen = [], set()
    for item in items:
        if isinstance(item, dict):
            text, start, duration = item.get("text", ""), item.get("start", 0), item.get("duration", 0.1)
        else:
            text, start, duration = getattr(item, "text", ""), getattr(item, "start", 0), getattr(item, "duration", 0.1)
        text = _clean(str(text))
        start = float(start)
        duration = max(0.1, float(duration))
        key = re.sub(r"\W+", "", text.casefold())
        if text and key not in seen:
            seen.add(key)
            result.append({"text": text, "start": start, "duration": duration, "end": start + duration, "timestamp": format_clock(start)})
    return result


def _parse_vtt(content: str) -> list[dict]:
    segments = []
    for block in re.split(r"\n\s*\n", content.replace("\r", "")):
        match = re.search(r"(?P<start>[0-9:.]+)\s+-->\s+(?P<end>[0-9:.]+)\s*\n(?P<text>.+)", block, re.S)
        if not match:
            continue
        def seconds(value: str) -> float:
            parts = value.replace(",", ".").split(":")
            if len(parts) == 2:
                parts.insert(0, "0")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        start, end = seconds(match["start"]), seconds(match["end"])
        segments.append({"text": _clean(match["text"]), "start": start, "duration": max(0.1, end - start)})
    return _segments(segments)


def _metadata(url: str) -> dict:
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 30}) as dl:
            info = dl.extract_info(url, download=False)
        return {"title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or ""}
    except Exception:
        return {}


def extract_transcript(url: str, languages=DEFAULT_LANGUAGES) -> dict:
    video_id = extract_video_id(url)
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    metadata = _metadata(canonical)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcripts = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = transcripts.find_transcript(list(languages))
        except Exception:
            transcript = next(iter(transcripts), None)
        if transcript is None:
            raise TranscriptError("Nenhuma transcrição acessível foi encontrada.")
        fetched = transcript.fetch()
        segments = _segments(fetched)
        if not segments:
            raise TranscriptError("A transcrição retornada está vazia.")
        return {"video_id": video_id, "video_url": canonical, "title": metadata.get("title") or f"Vídeo {video_id}", "channel": metadata.get("channel", ""), "language": getattr(transcript, "language", ""), "source": "youtube-transcript-api", "segments": segments}
    except Exception as api_error:
        try:
            import yt_dlp
            with tempfile.TemporaryDirectory(prefix="clipping_transcript_") as temporary:
                folder = Path(temporary)
                preferred_languages = [*languages, "pt.*", "en.*"]
                options = {"quiet": True, "no_warnings": True, "skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": preferred_languages, "subtitlesformat": "vtt", "outtmpl": str(folder / "%(id)s.%(ext)s"), "noplaylist": True, "socket_timeout": 30}
                with yt_dlp.YoutubeDL(options) as dl:
                    info = dl.extract_info(canonical, download=True)
                files = sorted(folder.glob(f"{video_id}*.vtt"))
                if not files:
                    raise TranscriptError("Nenhuma legenda acessível foi encontrada.")
                segments = _parse_vtt(files[0].read_text(encoding="utf-8", errors="replace"))
                if not segments:
                    raise TranscriptError("A legenda baixada não pôde ser interpretada.")
                return {"video_id": video_id, "video_url": canonical, "title": info.get("title") or metadata.get("title") or f"Vídeo {video_id}", "channel": info.get("channel") or info.get("uploader") or metadata.get("channel", ""), "language": "", "source": "yt-dlp", "segments": segments}
        except Exception as fallback_error:
            raise TranscriptError(f"Não foi possível obter a transcrição: {api_error} | {fallback_error}") from fallback_error


def export_files(job) -> dict[str, bytes]:
    segments = job.segments
    metadata = {"video_id": job.video_id, "video_url": job.video_url, "title": job.title, "channel": job.channel, "language": job.language, "source": job.source, "extracted_at": datetime.now(timezone.utc).isoformat(), "segment_count": len(segments)}
    base = f"transcricao_{job.video_id}"
    txt = "\n".join([f"TÍTULO: {job.title}", f"CANAL: {job.channel or 'Não identificado'}", f"LINK: {job.video_url}", f"ID DO VÍDEO: {job.video_id}", f"IDIOMA: {job.language or 'Não identificado'}", f"FONTE: {job.source}", "", "TRANSCRIÇÃO COM TIMESTAMPS", "=" * 34, "", *(f"[{item['timestamp']}] {item['text']}" for item in segments), ""])
    srt = "\n\n".join(f"{index}\n{format_clock(item['start'], True)} --> {format_clock(item['end'], True)}\n{item['text']}" for index, item in enumerate(segments, 1)) + "\n"
    return {f"{base}.txt": txt.encode(), f"{base}.json": json.dumps({"metadata": metadata, "segments": segments}, ensure_ascii=False, indent=2).encode(), f"{base}.srt": srt.encode(), "informacoes_do_video.json": json.dumps(metadata, ensure_ascii=False, indent=2).encode()}


def zip_files(job) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in export_files(job).items():
            archive.writestr(name, content)
    return buffer.getvalue()
