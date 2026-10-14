"""Offline source validation. Does not replace browser or live-service testing."""
import ast
import json
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.ids = set()
        self.inline = []
        self.sources = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, "Duplicate ID: " + attrs["id"]
            self.ids.add(attrs["id"])
        if tag == "script":
            if attrs.get("src"):
                self.sources.append(attrs["src"])
            else:
                self.current = ""

    def handle_data(self, data):
        if self.current is not None:
            self.current += data

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.inline.append(self.current)
            self.current = None


def main():
    for path in ROOT.rglob("*.py"):
        if "__pycache__" not in path.parts:
            ast.parse(path.read_text(), filename=str(path))
    json.loads((ROOT / "vercel.json").read_text())
    checked = 0
    with tempfile.TemporaryDirectory() as folder:
        for path in (ROOT / "static").glob("*.html"):
            parser = Page()
            parser.feed(path.read_text())
            for index, script in enumerate(parser.inline):
                target = Path(folder) / f"{path.stem}-{index}.js"
                target.write_text(script)
                subprocess.run(["node", "--check", str(target)], check=True)
                checked += 1
            for source in parser.sources:
                if source.startswith("/assets/"):
                    assert (ROOT / "static" / source.lstrip("/").split("?")[0]).is_file(), source
        for path in (ROOT / "static/assets").glob("*.js"):
            subprocess.run(["node", "--check", str(path)], check=True)
            checked += 1
            assert path.read_bytes() == (ROOT / "public/assets" / path.name).read_bytes(), "Run sync_storefront.py"
    assert (ROOT / "static/index.html").read_bytes() == (ROOT / "public/index.html").read_bytes(), "Run sync_storefront.py"
    print(f"Python and JSON valid; {checked} JavaScript blocks valid; HTML IDs, local script paths and public copies checked.")


if __name__ == "__main__":
    main()
