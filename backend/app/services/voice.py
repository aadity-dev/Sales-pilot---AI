"""Local speech-to-text (Whisper.cpp) and text-to-speech (macOS say) services."""
from __future__ import annotations

import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CURATED_VOICES: list[dict[str, str]] = [
    {"id": "Tara", "name": "Tara (Indian English)", "lang": "en-IN"},
    {"id": "Aman", "name": "Aman (Indian English)", "lang": "en-IN"},
    {"id": "Rishi", "name": "Rishi (Indian English)", "lang": "en-IN"},
    {"id": "Lekha", "name": "Lekha (Hindi)", "lang": "hi-IN"},
    {"id": "Samantha", "name": "Samantha (US English)", "lang": "en-US"},
    {"id": "Daniel", "name": "Daniel (UK English)", "lang": "en-GB"},
]

WHISPER_NOISE_RE = re.compile(
    r"^\s*(\[[^\]]*\]|\([^)]*\)|\*[^*]*\*)\s*$",
    re.IGNORECASE,
)

MIME_SUFFIX_MAP = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
}


class VoiceConfigError(RuntimeError):
    """Raised when optional local speech binaries or models are unavailable."""


class VoiceProcessingError(RuntimeError):
    """Raised when audio conversion, transcription, or synthesis fails."""


class VoiceTimeoutError(RuntimeError):
    """Raised when local audio processing exceeds its time limit."""


class EmptySpeechError(ValueError):
    """Raised when an audio clip contains no detectable speech."""


def get_whisper_paths() -> tuple[Path, Path] | None:
    whisper_bin = os.getenv("WHISPER_CPP_BIN", "").strip()
    whisper_model = os.getenv("WHISPER_MODEL_PATH", "").strip()
    if not whisper_bin or not whisper_model:
        return None
    bin_path, model_path = Path(whisper_bin), Path(whisper_model)
    if not bin_path.is_file() or not model_path.is_file():
        return None
    return bin_path, model_path


def is_stt_configured() -> bool:
    return get_whisper_paths() is not None


def _say_binary() -> Path | None:
    if platform.system() != "Darwin":
        return None
    say_path = Path("/usr/bin/say")
    return say_path if say_path.is_file() else None


def is_tts_configured() -> bool:
    return _say_binary() is not None


def list_local_voices() -> list[dict[str, str]]:
    say_bin = _say_binary()
    if not say_bin:
        return []
    try:
        res = subprocess.run([str(say_bin), "-v", "?"], capture_output=True, text=True, timeout=5, check=False)
        installed = res.stdout
    except (OSError, subprocess.SubprocessError):
        installed = ""
    voices = [v for v in CURATED_VOICES if not installed or re.search(rf"^{re.escape(v['id'])}\b", installed, re.MULTILINE)]
    return voices or [{"id": "Samantha", "name": "Samantha (Default)", "lang": "en-US"}]


def _resolve_suffix(filename: str | None, content_type: str | None) -> str:
    if content_type:
        base_mime = content_type.split(";")[0].strip().lower()
        if base_mime in MIME_SUFFIX_MAP:
            return MIME_SUFFIX_MAP[base_mime]
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".webm", ".mp4", ".m4a", ".ogg", ".wav", ".mp3", ".flac"}:
            return suffix
    return ".webm"


def _clean_whisper_transcript(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r"\[(?:BLANK_AUDIO|SILENCE|MUSIC|APPLAUSE|NOISE|INAUDIBLE)\]", "", line, flags=re.I)
        cleaned = re.sub(r"\((?:music|silence|applause|laughter|clicking|inaudible|sighs?)\)", "", cleaned, flags=re.I)
        cleaned = cleaned.strip()
        if cleaned and not WHISPER_NOISE_RE.match(cleaned):
            lines.append(cleaned)
    return " ".join(lines).strip()


def transcribe_audio_bytes(
    content: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    language: str = "auto",
) -> str:
    paths = get_whisper_paths()
    if not paths:
        raise VoiceConfigError(
            "Local speech recognition is not configured. Install whisper.cpp and set WHISPER_CPP_BIN and WHISPER_MODEL_PATH in .env. You can still use the text conversation and browser text-to-speech."
        )
    if not content:
        raise EmptySpeechError("No audio data was received.")

    bin_path, model_path = paths
    suffix = _resolve_suffix(filename, content_type)
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / f"input_audio{suffix}"
        wav_path = Path(temp_dir) / "converted_16k.wav"
        source_path.write_bytes(content)

        # Convert browser recordings (WebM/MP4/OGG) to 16 kHz mono WAV for whisper.cpp.
        try:
            conversion = subprocess.run(
                ["ffmpeg", "-y", "-i", str(source_path), "-ar", "16000", "-ac", "1", str(wav_path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VoiceConfigError("ffmpeg is required to convert browser audio for local transcription.") from exc
        except subprocess.TimeoutExpired as exc:
            raise VoiceTimeoutError("Audio conversion timed out.") from exc

        if conversion.returncode != 0 or not wav_path.exists():
            raise VoiceProcessingError("Audio conversion failed. Please record again.")

        whisper_language = {"en-IN": "en", "en-US": "en", "en-GB": "en", "hi-IN": "hi", "en": "en", "hi": "hi"}.get(language, "auto")
        if whisper_language == "hi":
            prompt = "नमस्ते, मुझे अपने बिज़नेस के लिए कस्टमर सपोर्ट ऑटोमेशन चाहिए और मेरा बजट पचास हजार रुपये है।"
        elif whisper_language == "en":
            prompt = "SalesPilot AI, customer support automation, budget rupees, timeline, decision maker, Shopify integration, demo appointment."
        else:
            prompt = "Hi SalesPilot AI, नमस्ते, customer support automation, budget 50,000 rupees, demo appointment."

        command = [
            str(bin_path),
            "-m", str(model_path),
            "-f", str(wav_path),
            "-l", whisper_language,
            "--prompt", prompt,
            "-nt", "-np",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        except subprocess.TimeoutExpired as exc:
            raise VoiceTimeoutError("Speech recognition timed out.") from exc

    if result.returncode != 0:
        raise VoiceProcessingError(f"Local transcription failed: {result.stderr[-500:]}")

    transcript = _clean_whisper_transcript(result.stdout)
    if not transcript:
        raise EmptySpeechError("No speech was detected in the recording.")
    return transcript


def format_for_speech(text: str) -> str:
    """Clean markdown and formatting symbols so spoken TTS sounds natural."""
    cleaned = text.strip()
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"₹\s*([\d,]+)", r"\1 rupees", cleaned)
    cleaned = re.sub(r"\b(\d{1,3})/100\b", r"\1 out of 100", cleaned)
    cleaned = re.sub(
        r"\n+Source:\s*([^\n]+)",
        lambda m: f" According to {m.group(1).strip().rstrip('.').removesuffix('.md').removesuffix('.txt').replace('_', ' ')}.",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def pick_voice(requested_voice: str | None, language: str) -> str:
    available = list_local_voices()
    available_ids = {v["id"] for v in available}
    if requested_voice and requested_voice in available_ids:
        return requested_voice
    lang_defaults = {
        "hi-IN": ["Lekha", "Tara", "Aman", "Rishi"],
        "en-IN": ["Tara", "Aman", "Rishi", "Samantha"],
        "en-US": ["Samantha", "Tara", "Rishi"],
        "en-GB": ["Daniel", "Tara", "Samantha"],
    }
    for candidate in lang_defaults.get(language, ["Tara", "Aman", "Rishi", "Samantha"]):
        if candidate in available_ids:
            return candidate
    return available[0]["id"] if available else "Samantha"


def synthesize_speech(text: str, voice: str | None = None, language: str = "en-IN") -> tuple[bytes, str]:
    say_bin = _say_binary()
    if not say_bin:
        raise VoiceConfigError("Local OS text-to-speech is only available on macOS. Browser speechSynthesis will be used instead.")

    spoken = format_for_speech(text)
    if not spoken:
        raise EmptySpeechError("Cannot synthesize empty text.")

    chosen_voice = pick_voice(voice, language)
    with tempfile.TemporaryDirectory() as temp_dir:
        wav_path = Path(temp_dir) / "speech.wav"
        try:
            res = subprocess.run(
                [
                    str(say_bin),
                    "-v", chosen_voice,
                    "-o", str(wav_path),
                    "--file-format=WAVE",
                    "--data-format=LEI16@22050",
                    spoken,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VoiceTimeoutError("Local speech synthesis timed out.") from exc

        if res.returncode != 0 or not wav_path.exists():
            raise VoiceProcessingError(f"Speech synthesis failed: {res.stderr.strip()}")
        return wav_path.read_bytes(), chosen_voice


def voice_capabilities() -> dict[str, Any]:
    return {
        "stt_configured": is_stt_configured(),
        "tts_configured": is_tts_configured(),
        "tts_engine": "macOS native voice (say)" if is_tts_configured() else "browser speechSynthesis",
        "voices": list_local_voices(),
    }
