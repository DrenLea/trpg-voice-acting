import asyncio
import hashlib
import json
import re
from pathlib import Path

import edge_tts

from .scriptfmt import Ev, parse_script

CACHE = Path("cache/wav")
FALLBACK = ["zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiaNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural"]
QUOTES = re.compile(r"[“”\"‘’「」『』]")
SPEAKABLE = re.compile(r"[一-鿿A-Za-z0-9]")


def voice_map(chars: dict) -> dict[str, dict]:
    vm = {"旁白": chars["narrator"]}
    used = {chars["narrator"]["voice"]}
    for r in chars["roles"]:
        vm[r["name"]] = r
        for a in r.get("aliases", []):
            vm.setdefault(a, r)
        used.add(r.get("voice"))
    pool = [v for v in FALLBACK if v not in used]
    for r in chars["roles"]:
        if not r.get("voice"):
            r["voice"] = pool.pop(0) if pool else FALLBACK[0]
            print(f"  {r['name']} 无声线，暂用 {r['voice']}")
    return vm


def key(cfg: dict, text: str) -> str:
    return hashlib.sha1(f"{cfg['voice']}|{cfg.get('rate', '0%')}|{cfg.get('pitch', '0Hz')}|{text}".encode()).hexdigest()


def _signed(v: str | None, unit: str) -> str:
    v = (v or "").strip() or f"0{unit}"
    return v if v[0] in "+-" else "+" + v


async def _one(sem: asyncio.Semaphore, cfg: dict, text: str, out: Path) -> None:
    async with sem:
        for _ in range(3):
            try:
                await edge_tts.Communicate(
                    text, cfg["voice"], rate=_signed(cfg.get("rate"), "%"), pitch=_signed(cfg.get("pitch"), "Hz")
                ).save(str(out))
                return
            except Exception as e:  # noqa: BLE001
                err = e
        raise RuntimeError(f"tts failed for {cfg['voice']}: {text[:60]!r}") from err


def synth(script: Path, chars: dict) -> list[tuple[Ev, Path | None]]:
    """返回事件序列；line 事件附带音频路径。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    vm = voice_map(chars)
    evs = parse_script(script)
    jobs: list[tuple[dict, str, Path]] = []
    result: list[tuple[Ev, Path | None]] = []
    for e in evs:
        if e.kind != "line":
            result.append((e, None))
            continue
        cfg = vm.get(e.a)
        if cfg is None:
            print(f"  未知角色 {e.a}，用旁白声线")
            cfg = vm["旁白"]
        text = QUOTES.sub("", e.b).replace("\n", "，")
        if not SPEAKABLE.search(text):
            continue
        p = CACHE / f"{key(cfg, text)}.mp3"
        if not p.exists() or p.stat().st_size < 1024:
            jobs.append((cfg, text, p))
        result.append((e, p))

    async def run() -> None:
        sem = asyncio.Semaphore(8)
        await asyncio.gather(*(_one(sem, c, t, p) for c, t, p in jobs))

    if jobs:
        asyncio.run(run())
    print(f"tts: {len(jobs)} new, {sum(1 for e, p in result if p) - len(jobs)} cached")
    return result


def load_chars(work: Path) -> dict:
    return json.loads((work / "characters.json").read_text(encoding="utf-8"))
