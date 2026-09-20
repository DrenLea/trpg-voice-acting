"""Openverse 音频检索（聚合 Freesound 音效 + Jamendo 音乐，无需密钥）。"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.openverse.org/v1/audio/"
HDR = {"User-Agent": "trpgv/0.1 (https://github.com/trpgv)"}
ASSETS = Path("assets")

# 中文关键词 → 英文检索词（音效/BGM 描述里出现即命中）
ZH2EN = {
    "推门": "door open", "开门": "door open", "关门": "door close", "敲门": "knock door", "门铃": "doorbell",
    "脚步": "footsteps", "跑步": "running footsteps", "雷": "thunder", "雨": "rain", "风": "wind",
    "电话": "telephone ring", "拨号": "rotary phone dial", "挂断": "phone hang up", "纸": "paper rustle",
    "翻书": "page turn", "倒茶": "pouring tea", "倒水": "pouring water", "杯": "glass clink", "落地": "object drop",
    "玻璃": "glass break", "马车": "horse carriage", "马蹄": "horse hooves", "钟": "clock tick", "钟声": "church bell",
    "枪": "gunshot", "尖叫": "scream", "心跳": "heartbeat", "火": "fire crackling", "警笛": "siren",
    "街": "street ambience", "人群": "crowd", "钥匙": "keys jingle", "抽屉": "drawer", "打字": "typewriter",
    "报纸": "newspaper", "火柴": "match strike", "点烟": "lighter", "汽车": "car engine", "鸟": "birds",
    "紧张": "dark tension cinematic", "悬疑": "suspense mystery", "恐怖": "horror ambient", "平静": "calm piano",
    "温馨": "warm acoustic", "悲伤": "sad piano", "日常": "light acoustic", "夜": "night ambient", "诡异": "eerie drone",
    "追逐": "chase action", "战斗": "battle epic", "回忆": "nostalgic piano", "城市": "city ambience",
    "衣架": "hanger drop", "开灯": "light switch", "反锁": "door lock", "捏皱": "paper crumple", "书写": "pen writing",
    "笔": "pen writing", "电流": "static electric hum", "接通": "phone pickup", "忙音": "phone busy tone",
    "听筒": "telephone handset", "轮椅": "wheelchair", "咔哒": "click", "引擎": "engine", "伞": "umbrella",
    "车轮": "carriage wheels", "弦乐": "strings", "轻快": "light playful", "俏皮": "playful quirky",
    "诙谐": "comedic quirky", "压抑": "dark oppressive", "舒缓": "calm soothing", "慵懒": "lazy afternoon jazz",
    "黄昏": "dusk", "滴答": "clock ticking", "轰鸣": "rumble", "室内乐": "chamber music", "小调": "light tune",
    "不安": "uneasy", "消防车": "fire truck", "停下": "stop", "减速": "slow down",
}


def to_query(desc: str) -> str:
    hits = [en for zh, en in ZH2EN.items() if zh in desc]
    if hits:
        return " ".join(dict.fromkeys(" ".join(hits[:3]).split()))
    return re.sub(r"[^\w ]", " ", desc).strip() or desc


def translate_batch(descs: list[str]) -> dict[str, str]:
    """未命中词典的描述一次性交给 haiku 转成 2-4 词英文检索词。"""
    if not descs:
        return {}
    from . import llm

    out = llm.ask("把每行中文音效/音乐描述转成 2-4 个英文检索词（Freesound/Jamendo 搜索用），只输出 `序号 词`，一行一个。",
                  "\n".join(f"{i} {d}" for i, d in enumerate(descs)), max_tokens=400)
    res = {}
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.+)", ln)
        if m and int(m[1]) < len(descs):
            res[descs[int(m[1])]] = m[2].strip().strip("`")
    return res


def search(q: str, kind: str, n: int = 8) -> list[dict]:
    params = {"q": q, "page_size": n}
    if kind == "sfx":
        params["source"] = "freesound"
    else:
        params["category"] = "music"
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=20) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]
    out = []
    for x in data.get("results", []):
        out.append({"id": x["id"], "title": x["title"], "url": x["url"], "source": x["source"],
                    "duration": (x.get("duration") or 0) // 1000, "license": x.get("license"),
                    "attribution": x.get("attribution", ""), "creator": x.get("creator", "")})
    return out


def download(url: str, kind: str, name: str, kws: list[str], attribution: str = "") -> Path:
    d = ASSETS / kind
    d.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w\-.一-鿿]", "_", name)
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    dst = d / name
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=120) as r:
        dst.write_bytes(r.read())
    tp = ASSETS / "tags.json"
    tags = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {"sfx": {}, "bgm": {}}
    tags.setdefault(kind, {})[name] = sorted(set(tags[kind].get(name, [])) | set(kws))
    tp.write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    if attribution:
        with (ASSETS / "ATTRIBUTION.txt").open("a", encoding="utf-8") as f:
            f.write(f"{kind}/{name}\t{attribution}\n")
    return dst


def auto_fill(missing: list[str], max_dur: dict[str, int] | None = None) -> list[dict]:
    """按 missing_assets.txt 每项自动取首个合适结果。返回每项处理结果。"""
    max_dur = max_dur or {"sfx": 30, "bgm": 600}
    from .mix import _find, _tags

    tags = _tags()
    items = []
    for item in missing:
        kind, _, desc = item.partition(": ")
        desc = desc.strip()
        if kind in ("sfx", "bgm") and desc and desc not in {d for _, d in items} and not _find(kind, desc, tags):
            items.append((kind, desc))
    # 词典未命中的（检索词仍含中文）批量交 LLM 翻译
    queries = {d: to_query(d) for _, d in items}
    queries.update(translate_batch([d for d, q in queries.items() if re.search(r"[一-鿿]", q)]))
    log = []
    for kind, desc in items:
        q0 = queries[desc]
        words = q0.split()
        c = None
        # 多词 AND 无结果时逐步去掉末尾词回退
        for k in range(len(words), 0, -1):
            q = " ".join(words[:k])
            cands = [c for c in search(q, kind, 10) if "error" not in c and c["duration"] > 0]
            fit = [c for c in cands if c["duration"] <= max_dur[kind]] or [c for c in cands if c["duration"] <= max_dur[kind] * 2]
            if fit:
                c = fit[0]
                break
        if not c:
            log.append({"desc": desc, "kind": kind, "q": q0, "ok": False})
            continue
        kws = [desc] + [zh for zh in ZH2EN if zh in desc]
        p = download(c["url"], kind, f"{q.replace(' ', '_')[:40]}_{c['id'][:6]}", kws, c["attribution"])
        log.append({"desc": desc, "kind": kind, "q": q, "ok": True, "file": p.name, "title": c["title"]})
    return log
