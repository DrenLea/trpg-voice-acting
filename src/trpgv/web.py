import json
import os
import re
import subprocess
import sys
from pathlib import Path

import edge_tts
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, tts

WORK, ASSETS = Path("work"), Path("assets")
STATIC = Path(__file__).parent / "static"
STEPS = ("parse", "clean", "chars", "script", "audio", "all")
app = FastAPI(title="trpgv")
procs: dict[str, subprocess.Popen] = {}


def _work(p: str) -> Path:
    d = WORK / p
    if not re.fullmatch(r"[\w\-一-鿿]+", p) or not d.is_dir():
        raise HTTPException(404, f"project {p} not found")
    return d


def _json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


# ---------- projects ----------
@app.get("/api/projects")
def projects():
    out = []
    for d in sorted(WORK.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True) if WORK.exists() else []:
        if not d.is_dir():
            continue
        pr = procs.get(d.name)
        running = pr is not None and pr.poll() is None
        has = {k: (d / f).exists() for k, f in
               [("lines", "lines.jsonl"), ("clean", "clean.jsonl"), ("chars", "characters.json"),
                ("script", "script.md"), ("audio", "out/full.mp3")]}
        state = "running" if running else "done" if all(has.values()) else "wip" if any(has.values()) else "new"
        if pr is not None and not running and pr.returncode:
            state = "failed"
        out.append({"name": d.name, "has": has, "state": state, "step": steps_of.get(d.name, ""),
                    "mtime": int(d.stat().st_mtime), "source": next((s.name for s in d.glob("source.*")), "")})
    return out


steps_of: dict[str, str] = {}


@app.post("/api/projects")
async def create(name: str, file: UploadFile):
    if not re.fullmatch(r"[\w\-一-鿿]+", name):
        raise HTTPException(400, "项目名只能包含中英文、数字、_ -")
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "log.txt").suffix.lower() or ".txt"
    dst = d / f"source{ext}"
    dst.write_bytes(await file.read())
    return {"name": name, "source": dst.name}


@app.get("/api/projects/{p}/status")
def status(p: str):
    d = _work(p)
    pr = procs.get(p)
    running = pr is not None and pr.poll() is None
    log = d / "log.txt"
    tail = log.read_text(encoding="utf-8", errors="replace")[-4000:] if log.exists() else ""
    if pr is not None and not running:
        tail += f"\n[exit {pr.returncode}]"
    return {"running": running, "step": steps_of.get(p, ""), "log": tail}


@app.delete("/api/projects/{p}")
def delete_project(p: str):
    import shutil

    d = _work(p)
    if (pr := procs.get(p)) and pr.poll() is None:
        raise HTTPException(409, "任务运行中，不能删除")
    shutil.rmtree(d)
    procs.pop(p, None)
    steps_of.pop(p, None)
    return {"ok": True}


@app.post("/api/projects/{p}/run/{step}")
def run(p: str, step: str, scene: int | None = None, smart: bool = False):
    d = _work(p)
    if step not in STEPS:
        raise HTTPException(400, "bad step")
    if (pr := procs.get(p)) and pr.poll() is None:
        raise HTTPException(409, "已有任务在运行")
    args = [sys.executable, "-m", "trpgv.cli", step]
    if step in ("parse", "all"):
        src = next(d.glob("source.*"), None)
        if not src:
            raise HTTPException(400, "未导入 log")
        args.append(str(src))
    args += ["-w", str(d)]
    if step == "clean":
        args.append("--llm")
    if step == "script":
        if scene:
            args += ["--scene", str(scene)]
        if smart or (not scene and config.load(d)["script_smart"]):
            args.append("--smart")
    log = (d / "log.txt").open("w", encoding="utf-8")
    steps_of[p] = step
    procs[p] = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=os.getcwd(),
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    return {"ok": True}


# ---------- characters / voices ----------
@app.get("/api/voices")
def voices():
    return _json(ASSETS / "voices.json", [])


@app.get("/api/projects/{p}/characters")
def get_chars(p: str):
    data = _json(_work(p) / "characters.json")
    if data is None:
        raise HTTPException(404, "尚未生成角色表")
    return data


@app.put("/api/projects/{p}/characters")
def put_chars(p: str, data: dict):
    (_work(p) / "characters.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


@app.get("/api/preview")
async def preview(voice: str, text: str = "你好，这是试听。", rate: str = "0%", pitch: str = "0Hz"):
    cfg = {"voice": voice, "rate": rate, "pitch": pitch}
    tts.CACHE.mkdir(parents=True, exist_ok=True)
    out = tts.CACHE / f"{tts.key(cfg, text)}.mp3"
    if not out.exists() or out.stat().st_size < 1024:
        await edge_tts.Communicate(text, voice, rate=tts._signed(rate, "%"), pitch=tts._signed(pitch, "Hz")).save(str(out))
    return FileResponse(out, media_type="audio/mpeg")


# ---------- script ----------
@app.get("/api/projects/{p}/scenes")
def scenes(p: str):
    d = _work(p)
    titles = dict(enumerate([t for _, t in _json(d / "scenes.json", [])], 1))
    return [{"n": int(f.stem), "title": titles.get(int(f.stem), ""), "text": f.read_text(encoding="utf-8")}
            for f in sorted((d / "scenes").glob("*.md"))] if (d / "scenes").exists() else []


class SceneBody(BaseModel):
    text: str


@app.put("/api/projects/{p}/scenes/{n}")
def put_scene(p: str, n: int, body: SceneBody):
    from . import script

    d = _work(p)
    (d / "scenes" / f"{n:02d}.md").write_text(body.text.strip() + "\n", encoding="utf-8")
    chars = _json(d / "characters.json")
    script.assemble(d, chars, [tuple(x) for x in _json(d / "scenes.json", [])])
    return {"ok": True}


@app.get("/api/projects/{p}/lines")
def lines(p: str, which: str = "clean"):
    f = _work(p) / ("clean.txt" if which == "clean" else "lines.jsonl")
    return {"text": f.read_text(encoding="utf-8") if f.exists() else ""}


# ---------- assets ----------
@app.get("/api/assets")
def assets():
    tags = _json(ASSETS / "tags.json", {"sfx": {}, "bgm": {}})
    out = {}
    for kind in ("sfx", "bgm"):
        files = {f.name for f in (ASSETS / kind).glob("*")} if (ASSETS / kind).exists() else set()
        items = {f: {"kws": kws, "exists": f in files} for f, kws in tags.get(kind, {}).items()}
        for f in files - set(items):
            items[f] = {"kws": [], "exists": True}
        out[kind] = items
    return out


@app.post("/api/assets/{kind}")
async def upload_asset(kind: str, file: UploadFile, kws: str = "", target: str = ""):
    if kind not in ("sfx", "bgm"):
        raise HTTPException(400)
    d = ASSETS / kind
    d.mkdir(parents=True, exist_ok=True)
    name = Path(target or file.filename or "x").name
    (d / name).write_bytes(await file.read())
    tags = _json(ASSETS / "tags.json", {"sfx": {}, "bgm": {}})
    words = [w.strip() for w in re.split(r"[,，\s]+", kws) if w.strip()]
    if words or name not in tags.setdefault(kind, {}):
        tags[kind][name] = sorted(set(tags[kind].get(name, [])) | set(words))
    (ASSETS / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


@app.put("/api/assets/{kind}/{name}/kws")
def put_kws(kind: str, name: str, body: SceneBody):
    tags = _json(ASSETS / "tags.json", {"sfx": {}, "bgm": {}})
    tags.setdefault(kind, {})[name] = [w for w in re.split(r"[,，\s]+", body.text) if w]
    (ASSETS / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True}


@app.get("/api/projects/{p}/missing")
def missing(p: str):
    f = _work(p) / "out" / "missing_assets.txt"
    return [x for x in f.read_text(encoding="utf-8").splitlines() if x] if f.exists() else []


@app.get("/api/openverse/search")
def ov_search(q: str, kind: str = "sfx", n: int = 8):
    from . import assets as ov

    eq = ov.to_query(q)
    if re.search(r"[一-鿿]", eq):
        eq = ov.translate_batch([q]).get(q, eq)
    used, res = ov.search_relaxed(eq, kind, n)
    return {"query": used, "results": res}


class Grab(BaseModel):
    url: str
    kind: str
    name: str
    kws: str = ""
    attribution: str = ""


@app.post("/api/openverse/grab")
def ov_grab(g: Grab):
    from . import assets as ov

    if g.kind not in ("sfx", "bgm"):
        raise HTTPException(400)
    p = ov.download(g.url, g.kind, g.name, [w for w in re.split(r"[,，\s]+", g.kws) if w], g.attribution)
    return {"ok": True, "file": p.name}


@app.post("/api/projects/{p}/autofill")
def autofill(p: str):
    from . import assets as ov

    return ov.auto_fill(missing(p))


@app.get("/api/projects/{p}/out")
def outputs(p: str):
    o = _work(p) / "out"
    return [f.name for f in sorted(o.glob("*.mp3"))] if o.exists() else []


# ---------- config / cues ----------
@app.get("/api/projects/{p}/config")
def get_config(p: str):
    return {"values": config.load(_work(p)), "defaults": config.DEFAULTS}


@app.put("/api/projects/{p}/config")
def put_config(p: str, data: dict):
    return config.save(_work(p), data)


@app.get("/api/projects/{p}/cues")
def cues(p: str):
    """剧本中出现的全部 BGM/SFX 标注，按顺序，附当前解析到的文件。"""
    from .mix import _tags, resolve
    from .scriptfmt import parse_script

    d = _work(p)
    sp = d / "script.md"
    if not sp.exists():
        return []
    tags, ov = _tags(), config.load_cues(d)
    out, scene = [], ""
    for i, e in enumerate(parse_script(sp)):
        if e.kind == "scene":
            scene = f"第{e.a}幕 {e.b}"
        elif e.kind in ("bgm", "sfx"):
            if e.kind == "bgm" and e.a.strip() in ("无", "停止", "none"):
                continue
            f, db, src = resolve(e.kind, e.a, tags, ov)
            out.append({"i": i, "kind": e.kind, "desc": e.a, "scene": scene,
                        "file": f"{f.parent.name}/{f.name}" if f else "", "db": db, "src": src})
    return out


class CueBody(BaseModel):
    kind: str
    desc: str
    file: str | None = None   # None=自动匹配；""=静音；"bgm/x.mp3"=指定
    db: int | None = None


@app.put("/api/projects/{p}/cues")
def put_cue(p: str, b: CueBody):
    d = _work(p)
    cs = config.load_cues(d)
    k = f"{b.kind}:{b.desc}"
    if b.file is None and b.db is None:
        cs.pop(k, None)
    else:
        cs[k] = {"file": b.file, "db": b.db}
    config.save_cues(d, cs)
    return {"ok": True}


WORK.mkdir(exist_ok=True)
ASSETS.mkdir(exist_ok=True)
app.mount("/work", StaticFiles(directory=WORK), name="work")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
