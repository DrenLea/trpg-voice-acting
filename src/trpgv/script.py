import json
import re
from pathlib import Path

from . import llm
from .characters import KP_ROLES
from .parse import Line

SCENE_LINE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$", re.M)


def split_scenes(lines: list[Line]) -> list[tuple[int, str]]:
    user = "\n".join(f"{ln.i}|{ln.role}|{ln.text[:40].replace(chr(10), ' ')}" for ln in lines)
    found = [(int(m[1]), m[2]) for m in SCENE_LINE.finditer(llm.ask(llm.prompt("scenes"), user))]
    valid = {ln.i for ln in lines}
    found = [(i, t) for i, t in found if i in valid]
    if not found or found[0][0] != lines[0].i:
        found.insert(0, (lines[0].i, "开场"))
    return found


def _chars_block(chars: dict) -> str:
    rows = [f"- 旁白：{chars['narrator'].get('traits', '')}"]
    for r in chars["roles"]:
        al = "、".join(r.get("aliases", []))
        rows.append(f"- {r['name']}（{r['type']}{'，别名 ' + al if al else ''}）：{r.get('traits', '')}")
    return "\n".join(rows)


TAG = re.compile(r"^【([^】]+?)(?:·[^】]*)?】\s*(.*)$")


def normalize(text: str) -> str:
    """去掉多余标题，标签与正文合并到同一行，剥离 ·内心 之类后缀。"""
    out: list[str] = []
    pending: str | None = None
    for raw in text.splitlines():
        s = raw.rstrip()
        if not s:
            continue
        if s.startswith("#") and out:
            continue
        if m := TAG.match(s):
            if pending:
                out.append(pending)
            pending = f"【{m[1]}】{m[2]}".rstrip()
            continue
        if pending is not None and not (s.startswith("[") or s.startswith("「")):
            pending = f"{pending}{s}" if pending.endswith("】") else f"{pending}\n{s}"
            continue
        if pending:
            out.append(pending)
            pending = None
        out.append(s)
    if pending:
        out.append(pending)
    return "\n".join(out) + "\n"


BAD = re.compile(r"^【(KP|kp|舞台说明|场景|旁白·|[^】]*·(内心|独白|OS))|骰子|过个|过一个|检定|(侦查|闪避|意志|幸运)(成功|失败)", re.M)


def _check(out: str, roles: set[str]) -> list[str]:
    errs = []
    if "【旁白】" not in out:
        errs.append("缺少【旁白】叙述")
    if m := BAD.findall(out):
        errs.append(f"包含禁止内容: {', '.join(sorted({x[0] or x[1] or x[2] for x in m})[:5])}")
    bad_tags = {t for t in re.findall(r"^【([^】]+)】", out, re.M) if t not in roles and not t.startswith("？")}
    if bad_tags:
        errs.append(f"未知标签: {', '.join(sorted(bad_tags)[:5])}")
    return errs


def render_scene(n: int, title: str, lines: list[Line], chars: dict, model: str) -> str:
    system = llm.prompt("script") + "\n\n## 角色表\n" + _chars_block(chars)
    roles = {"旁白"} | {r["name"] for r in chars["roles"]}
    body = "\n".join(
        (f"KP: {ln.text}" if ln.role in KP_ROLES else f"玩家[{ln.role}]: {ln.text}") for ln in lines
    )
    user = (
        f"<记录>\n{body}\n</记录>\n\n"
        f"以上是跑团原始记录，不是对话请求。请改写为第{n}幕剧本，标题「{title}」，"
        f"严格按输出格式：所有描述归【旁白】，KP 里的 NPC 台词归对应 NPC，玩家动作描述改为旁白第三人称。"
    )
    prefill = f"## 第{n}幕 · {title}\n"
    errs: list[str] = []
    for attempt in range(3):
        u = user if not errs else user + "\n\n上一次输出的问题：" + "；".join(errs) + "。请修正后重新输出整幕。"
        out = normalize(llm.ask(system, u, model=model, max_tokens=4000, prefill=prefill))
        errs = _check(out, roles)
        if not errs:
            return out
        print(f"  scene {n} attempt {attempt + 1}: {errs}")
    return out


def build(work: Path, model: str = llm.CHEAP, only: int | None = None) -> Path:
    from .parse import load

    lines = load(work / "clean.jsonl")
    chars = json.loads((work / "characters.json").read_text(encoding="utf-8"))
    scenes_path = work / "scenes.json"
    if scenes_path.exists():
        scenes = [tuple(x) for x in json.loads(scenes_path.read_text(encoding="utf-8"))]
    else:
        scenes = split_scenes(lines)
        scenes_path.write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding="utf-8")

    sdir = work / "scenes"
    sdir.mkdir(exist_ok=True)
    bounds = [s[0] for s in scenes] + [lines[-1].i + 1]
    for n, (start, title) in enumerate(scenes, 1):
        out = sdir / f"{n:02d}.md"
        if only is not None:
            if n != only:
                continue
        elif out.exists():
            continue
        chunk = [ln for ln in lines if start <= ln.i < bounds[n]]
        out.write_text(render_scene(n, title, chunk, chars, model), encoding="utf-8")
        print(f"scene {n:02d} {title} ({len(chunk)} lines) -> {out}")

    register_unknown(work, chars)
    return assemble(work, chars, scenes)


def register_unknown(work: Path, chars: dict) -> None:
    """把剧本里 【？X】 的新 NPC 登记进 characters.json（voice 留空）并去掉问号。"""
    known = {r["name"] for r in chars["roles"]}
    new: set[str] = set()
    for p in sorted((work / "scenes").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        found = set(re.findall(r"^【？([^】]+)】", t, re.M))
        if found:
            p.write_text(re.sub(r"^【？([^】]+)】", r"【\1】", t, flags=re.M), encoding="utf-8")
            new |= found - known
    if new:
        for name in sorted(new):
            chars["roles"].append({"name": name, "aliases": [], "type": "NPC", "player": "KP",
                                   "traits": "", "tone": "", "voice": "", "rate": "0%", "pitch": "0Hz"})
        (work / "characters.json").write_text(json.dumps(chars, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"新增未分配声线的 NPC: {', '.join(sorted(new))} → 请在 characters.json 填 voice")


def assemble(work: Path, chars: dict, scenes: list[tuple[int, str]]) -> Path:
    head = ["# 广播剧剧本", "", "## 大纲"]
    head += [f"{n}. {t}" for n, (_, t) in enumerate(scenes, 1)]
    head += ["", "## 角色与声线", "| 角色 | 身份 | 性格 | 声线倾向 | voice |", "|---|---|---|---|---|"]
    nr = chars["narrator"]
    head.append(f"| 旁白 | KP | {nr.get('traits', '')} | {nr.get('tone', '')} | {nr['voice']} |")
    for r in chars["roles"]:
        head.append(f"| {r['name']} | {r['type']} | {r.get('traits', '')} | {r.get('tone', '')} | {r['voice']} |")
    parts = [p.read_text(encoding="utf-8").strip() for p in sorted((work / "scenes").glob("*.md"))]
    out = work / "script.md"
    out.write_text("\n".join(head) + "\n\n" + "\n\n".join(parts) + "\n", encoding="utf-8")
    return out
