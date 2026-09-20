import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

HEADER = re.compile(r"^<\[(?P<player>[^\]]+)\](?P<role>[^>]*)>:(?P<text>.*)$")


@dataclass
class Line:
    i: int
    player: str
    role: str
    text: str


def read_text(path: Path) -> str:
    if path.suffix.lower() != ".docx":
        return path.read_text(encoding="utf-8")
    import html
    import zipfile

    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    return "\n".join(html.unescape(re.sub(r"<[^>]+>", "", p)) for p in paras)


def parse(path: Path) -> list[Line]:
    lines: list[Line] = []
    cur: Line | None = None
    for raw in read_text(path).splitlines():
        s = raw.strip()
        if not s:
            continue
        m = HEADER.match(s)
        if m:
            cur = Line(len(lines), m["player"].strip(), m["role"].strip(), m["text"].strip())
            lines.append(cur)
        elif cur:
            cur.text = f"{cur.text}\n{s}" if cur.text else s
    return lines


def dump(lines: list[Line], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(asdict(ln), ensure_ascii=False) + "\n")


def load(path: Path) -> list[Line]:
    return [Line(**json.loads(s)) for s in path.read_text(encoding="utf-8").splitlines() if s]
