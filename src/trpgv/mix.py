import json
from pathlib import Path

import imageio_ffmpeg
import pydub.audio_segment
from pydub import AudioSegment

from .scriptfmt import Ev

AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
# imageio-ffmpeg 不带 ffprobe；pydub 没有探测信息时会按默认参数解码，对 mp3/wav 足够
pydub.audio_segment.mediainfo_json = lambda *a, **k: {}

ASSETS = Path("assets")
GAP, SCENE_GAP, SFX_GAP = 400, 1500, 300
BGM_DB, FADE = -18, 2000


def _tags() -> dict[str, list[str]]:
    p = ASSETS / "tags.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _find(kind: str, desc: str, tags: dict) -> Path | None:
    d = ASSETS / kind
    for f, kws in tags.get(kind, {}).items():
        if any(k in desc for k in kws) and (d / f).exists():
            return d / f
    for f in d.glob("*") if d.exists() else []:
        if f.stem in desc:
            return f
    return None


def _bgm(seg: AudioSegment, length: int) -> AudioSegment:
    while len(seg) < length:
        seg += seg
    return (seg[:length] + BGM_DB).fade_in(FADE).fade_out(FADE)


def mix(events: list[tuple[Ev, Path | None]], out_dir: Path) -> Path:
    tags = _tags()
    missing: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    full = AudioSegment.empty()
    scene_audio: list[tuple[str, AudioSegment]] = []
    cur = AudioSegment.empty()
    cur_title = "00"
    bgm_start: int | None = None
    bgm_file: Path | None = None

    def close_bgm(track: AudioSegment) -> AudioSegment:
        nonlocal bgm_start, bgm_file
        if bgm_file and bgm_start is not None and len(track) > bgm_start:
            music = _bgm(AudioSegment.from_file(bgm_file), len(track) - bgm_start)
            track = track.overlay(music, position=bgm_start)
        bgm_start, bgm_file = None, None
        return track

    def flush() -> None:
        nonlocal cur, full
        if len(cur) == 0:
            return
        cur = close_bgm(cur)
        scene_audio.append((cur_title, cur))
        full += cur + AudioSegment.silent(SCENE_GAP)
        cur = AudioSegment.empty()

    for e, p in events:
        if e.kind == "scene":
            flush()
            cur_title = f"{int(e.a):02d}_{e.b}"
        elif e.kind == "line" and p:
            cur += AudioSegment.from_file(p) + AudioSegment.silent(GAP)
        elif e.kind == "sfx":
            f = _find("sfx", e.a, tags)
            if f:
                cur += AudioSegment.from_file(f) + AudioSegment.silent(SFX_GAP)
            else:
                missing.append(f"sfx: {e.a}")
        elif e.kind == "bgm":
            cur = close_bgm(cur)
            if e.a.strip() in ("无", "停止", "none"):
                continue
            f = _find("bgm", e.a, tags)
            if f:
                bgm_start, bgm_file = len(cur), f
            else:
                missing.append(f"bgm: {e.a}")
    flush()

    for title, seg in scene_audio:
        seg.export(out_dir / f"{title}.mp3", format="mp3", bitrate="128k")
    final = out_dir / "full.mp3"
    full.export(final, format="mp3", bitrate="128k")
    mp = out_dir / "missing_assets.txt"
    if missing:
        mp.write_text("\n".join(dict.fromkeys(missing)), encoding="utf-8")
        print(f"缺素材 {len(set(missing))} 项 → {mp}")
    elif mp.exists():
        mp.unlink()
    print(f"total {len(full) / 1000:.0f}s -> {final}")
    return final
