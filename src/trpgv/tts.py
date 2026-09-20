import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

import edge_tts

from .scriptfmt import Ev, parse_script

CACHE = Path("cache/wav")
FALLBACK = ["zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiaNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural"]
QUOTES = re.compile(r"[“”\"‘’「」『』]")
SPEAKABLE = re.compile(r"[一-鿿A-Za-z0-9]")
FIELDS = ("voice", "rate", "pitch", "style", "role")
ROLES = ("Girl", "Boy", "YoungAdultFemale", "YoungAdultMale", "OlderAdultFemale", "OlderAdultMale",
         "SeniorFemale", "SeniorMale")
AZURE_FMT = "audio-24khz-48kbitrate-mono-mp3"


def engine_from(cfg: dict) -> dict:
    """从项目 config 取 TTS 引擎参数；密钥只走环境变量（TTS_API_KEY / AZURE_SPEECH_KEY）。"""
    from .llm import _load_env

    _load_env()
    e = cfg.get("tts_engine", "edge")
    return {"engine": e, "base_url": cfg.get("tts_base_url", "").rstrip("/"), "model": cfg.get("tts_model", ""),
            "key": os.environ.get("AZURE_SPEECH_KEY" if e == "azure" else "TTS_API_KEY", ""),
            "region": os.environ.get("AZURE_SPEECH_REGION", "")}


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


def line_key(role: str, text: str) -> str:
    return hashlib.sha1(f"{role}|{text}".encode()).hexdigest()[:12]


def key(cfg: dict, text: str, eng: dict | None = None) -> str:
    e = eng or {}
    parts = [cfg["voice"], cfg.get("rate") or "0%", cfg.get("pitch") or "0Hz", text]
    if e.get("engine", "edge") != "edge":  # edge 保持旧键格式，已有缓存不失效
        parts = [e["engine"], e.get("model", ""), cfg.get("style") or "", cfg.get("role") or "", *parts]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _signed(v: str | None, unit: str) -> str:
    v = (v or "").strip() or f"0{unit}"
    return v if v[0] in "+-" else "+" + v


def _speed(rate: str | None) -> float:
    m = re.search(r"[-+]?\d+(\.\d+)?", rate or "")
    return round(1 + float(m[0]) / 100, 3) if m else 1.0


def _post(url: str, data: bytes, hdr: dict, out: Path) -> None:
    import urllib.request

    req = urllib.request.Request(url, data, hdr)
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())


def _auth(eng: dict) -> dict:
    return {"Authorization": f"Bearer {eng['key']}"} if eng.get("key") else {}


def get_json(url: str, eng: dict, timeout: int = 5):
    import urllib.request

    with urllib.request.urlopen(urllib.request.Request(url, headers=_auth(eng)), timeout=timeout) as r:
        return json.loads(r.read())


def post_raw(url: str, body: dict, eng: dict, timeout: int = 120) -> tuple[bytes, dict]:
    """POST JSON，返回 (响应字节, 小写键的响应头)。"""
    import urllib.request

    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **_auth(eng)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), {k.lower(): v for k, v in r.headers.items()}


def azure_ssml(cfg: dict, text: str) -> str:
    from xml.sax.saxutils import escape

    body = f"<prosody rate='{_signed(cfg.get('rate'), '%')}' pitch='{_signed(cfg.get('pitch'), 'Hz')}'>{escape(text)}</prosody>"
    attrs = "".join(f" {k}='{cfg[k]}'" for k in ("style", "role") if cfg.get(k))
    if attrs:
        body = f"<mstts:express-as{attrs}>{body}</mstts:express-as>"
    return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            "xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='zh-CN'>"
            f"<voice name='{cfg['voice']}'>{body}</voice></speak>")


def azure_base(region: str) -> str:
    """region 可填完整地址（如 Azure 中国 https://xx.tts.speech.azure.cn）。"""
    return region.rstrip("/") if "://" in region else f"https://{region}.tts.speech.microsoft.com"


async def speak(eng: dict, cfg: dict, text: str, out: Path) -> None:
    e = eng.get("engine", "edge")
    if e == "edge":
        await edge_tts.Communicate(text, cfg["voice"], rate=_signed(cfg.get("rate"), "%"),
                                   pitch=_signed(cfg.get("pitch"), "Hz")).save(str(out))
        return
    if e == "azure":
        if not (eng.get("key") and eng.get("region")):
            raise RuntimeError("tts_engine=azure 需要在 .env 填 AZURE_SPEECH_KEY 和 AZURE_SPEECH_REGION（如 eastasia）")
        hdr = {"Ocp-Apim-Subscription-Key": eng["key"], "Content-Type": "application/ssml+xml",
               "X-Microsoft-OutputFormat": AZURE_FMT, "User-Agent": "trpgv"}
        await asyncio.to_thread(_post, f"{azure_base(eng['region'])}/cognitiveservices/v1",
                                azure_ssml(cfg, text).encode(), hdr, out)
        return
    if not eng.get("base_url"):
        raise RuntimeError("tts_engine=openai 需要在设置里填 tts_base_url（如 http://127.0.0.1:8880/v1）")
    body = {"model": eng.get("model") or "tts-1", "input": text, "voice": cfg["voice"],
            "speed": _speed(cfg.get("rate")), "response_format": "mp3"}
    if cfg.get("style"):
        body["instructions"] = cfg["style"]
    hdr = {"Content-Type": "application/json"}
    if eng.get("key"):
        hdr["Authorization"] = f"Bearer {eng['key']}"
    await asyncio.to_thread(_post, f"{eng['base_url']}/audio/speech", json.dumps(body).encode(), hdr, out)


async def _one(sem: asyncio.Semaphore, eng: dict, cfg: dict, text: str, out: Path) -> None:
    async with sem:
        for _ in range(3):
            try:
                await speak(eng, cfg, text, out)
                return
            except Exception as e:  # noqa: BLE001
                err = e
        raise RuntimeError(f"tts failed for {cfg['voice']}: {text[:60]!r}") from err


def line_cfg(vm: dict, role: str, text: str, overrides: dict, engine: str = "edge") -> dict:
    """角色声线 + 行级覆盖（只覆盖非空字段），并去掉当前引擎不支持的字段。"""
    base = vm.get(role) or vm["旁白"]
    cfg = {k: base.get(k) or "" for k in FIELDS}
    for k, v in overrides.get(line_key(role, text), {}).items():
        if k in FIELDS and v:
            cfg[k] = v
    if engine == "openai":  # style 是自由文本指令，空则用语气
        cfg["style"], cfg["role"] = cfg["style"] or base.get("tone") or "", ""
    elif engine != "azure":  # edge 无风格/年龄，不入缓存键
        cfg["style"] = cfg["role"] = ""
    return cfg


def synth(script: Path, chars: dict, concurrency: int = 8, eng: dict | None = None,
          overrides: dict | None = None) -> list[tuple[Ev, Path | None]]:
    """返回事件序列；line 事件附带音频路径。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    eng, overrides = eng or {"engine": "edge"}, overrides or {}
    vm = voice_map(chars)
    evs = parse_script(script)
    jobs: list[tuple[dict, str, Path]] = []
    result: list[tuple[Ev, Path | None]] = []
    for e in evs:
        if e.kind != "line":
            result.append((e, None))
            continue
        if e.a not in vm:
            print(f"  未知角色 {e.a}，用旁白声线")
        cfg = line_cfg(vm, e.a, e.b, overrides, eng["engine"])
        text = QUOTES.sub("", e.b).replace("\n", "，")
        if not SPEAKABLE.search(text):
            continue
        p = CACHE / f"{key(cfg, text, eng)}.mp3"
        if not p.exists() or p.stat().st_size < 1024:
            jobs.append((cfg, text, p))
        result.append((e, p))

    async def run() -> None:
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(*(_one(sem, eng, c, t, p) for c, t, p in jobs))

    if jobs:
        asyncio.run(run())
    print(f"tts[{eng['engine']}]: {len(jobs)} new, {sum(1 for e, p in result if p) - len(jobs)} cached")
    return result


def load_chars(work: Path) -> dict:
    return json.loads((work / "characters.json").read_text(encoding="utf-8"))
