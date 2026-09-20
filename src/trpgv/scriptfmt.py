import re
from dataclasses import dataclass
from pathlib import Path

TAG = re.compile(r"^【([^】]+)】(.*)$")
SCENE = re.compile(r"^## 第(\d+)幕 · (.+)$")
BGM = re.compile(r"^「BGM[:：]\s*(.+?)」$")
SFX = re.compile(r"^\[(.+?)\]$")


@dataclass
class Ev:
    kind: str  # scene | bgm | sfx | line
    a: str = ""
    b: str = ""


def parse_script(path: Path) -> list[Ev]:
    evs: list[Ev] = []
    cur: Ev | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if m := SCENE.match(s):
            cur = None
            evs.append(Ev("scene", m[1], m[2]))
        elif m := BGM.match(s):
            cur = None
            evs.append(Ev("bgm", m[1]))
        elif m := SFX.match(s):
            cur = None
            evs.append(Ev("sfx", m[1]))
        elif m := TAG.match(s):
            cur = Ev("line", m[1], m[2].strip())
            evs.append(cur)
        elif cur and cur.kind == "line":
            cur.b += "\n" + s
        elif s.startswith("#") or s.startswith("|") or evs and evs[-1].kind != "scene" and not evs:
            continue
    return [e for e in evs if e.kind != "line" or e.b.strip()]
