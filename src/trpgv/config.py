import json
from pathlib import Path

DEFAULTS = {
    "gap_ms": 400,          # 句间静音
    "scene_gap_ms": 1500,   # 幕间静音
    "sfx_gap_ms": 300,      # 音效后静音
    "bgm_db": -18,          # BGM 相对音量
    "sfx_db": 0,            # 音效相对音量
    "fade_ms": 2000,        # BGM 淡入淡出
    "bitrate": "128k",
    "tts_concurrency": 8,
    "script_smart": False,  # 剧本默认用 sonnet
}


def load(work: Path) -> dict:
    p = work / "config.json"
    cfg = dict(DEFAULTS)
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def save(work: Path, cfg: dict) -> dict:
    clean = {k: cfg[k] for k in DEFAULTS if k in cfg}
    (work / "config.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    return load(work)


def load_cues(work: Path) -> dict:
    """{ "bgm:描述" | "sfx:描述": {"file": "bgm/x.mp3" | "", "db": int|None} }；file 为空表示静音。"""
    p = work / "cues.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_cues(work: Path, cues: dict) -> None:
    (work / "cues.json").write_text(json.dumps(cues, ensure_ascii=False, indent=1), encoding="utf-8")
