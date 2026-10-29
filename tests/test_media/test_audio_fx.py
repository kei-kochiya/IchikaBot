import shutil
import wave
from pathlib import Path

import pytest
from pydub.generators import Sine

from utils.media import audio_fx

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


@pytest.fixture
def track(tmp_path, monkeypatch):
    """A 75 second 'song' (long enough that the safe zones leave room to pick a clip)."""
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    monkeypatch.setattr(audio_fx, "TEMP_DIR", clips_dir)

    path = tmp_path / "song.wav"
    Sine(440).to_audio_segment(duration=75_000).export(str(path), format="wav").close()
    return str(path)


def _seconds(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def test_clip_has_the_configured_length(track):
    path, effect = audio_fx.prepare_clip(track)

    assert path is not None and Path(path).exists()
    assert path.endswith(".wav")
    assert _seconds(path) == pytest.approx(20.0, abs=0.1)
    assert effect == "Bình thường"


def test_normal_clip_never_decodes_the_whole_track(track, monkeypatch):
    def full_decode(*args, **kwargs):
        raise AssertionError("whole track was decoded")

    monkeypatch.setattr(audio_fx.AudioSegment, "from_file", full_decode)

    path, _ = audio_fx.prepare_clip(track)

    assert path is not None
    assert _seconds(path) == pytest.approx(20.0, abs=0.1)


def test_clip_start_stays_inside_the_safe_zones(track, monkeypatch):
    starts = []
    real_extract = audio_fx._extract_clip

    def spy(file_path, start_ms, length_ms):
        starts.append(start_ms)
        return real_extract(file_path, start_ms, length_ms)

    monkeypatch.setattr(audio_fx, "_extract_clip", spy)
    for _ in range(5):
        audio_fx.prepare_clip(track)

    latest = 75_000 - audio_fx.SONG_SAFE_ZONE - audio_fx.SONG_CLIP_DURATION
    assert all(audio_fx.SONG_SAFE_ZONE <= s <= latest for s in starts)


def test_falls_back_to_full_decode_when_probing_fails(track, monkeypatch):
    monkeypatch.setattr(audio_fx, "_probe_duration_ms", lambda _path: None)

    path, _ = audio_fx.prepare_clip(track)

    assert path is not None
    assert _seconds(path) == pytest.approx(20.0, abs=0.1)


def test_short_track_is_clipped_from_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_fx, "TEMP_DIR", tmp_path)
    short = tmp_path / "short.wav"
    Sine(440).to_audio_segment(duration=8_000).export(str(short), format="wav").close()

    path, _ = audio_fx.prepare_clip(str(short))

    assert path is not None
    assert _seconds(path) == pytest.approx(8.0, abs=0.1)


@pytest.mark.parametrize(
    ("variant", "expected_seconds"),
    [("reverse", 20.0), ("slow", 20.0 / 0.75), ("fast", 20.0 / 1.5)],
)
def test_variants_apply_their_effect(track, variant, expected_seconds):
    path, effect = audio_fx.prepare_clip(track, variant)

    assert path is not None
    assert effect != "Bình thường"
    assert _seconds(path) == pytest.approx(expected_seconds, abs=0.5)


def test_missing_file_returns_nothing(tmp_path):
    assert audio_fx.prepare_clip(str(tmp_path / "does-not-exist.mp3")) == (None, None)
