#!/usr/bin/env python3
import json
import os
import re
import shutil
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
BACKUP_DIR = ROOT / ".textupdater-backups"
PORT = int(os.environ.get("TEXTUPDATER_PORT", "5600"))
UI_FILE = ROOT / "textupdater.html"

SLOTS = [
    {
        "id": "header-slider",
        "label": "Header Slider",
        "description": "Main landing slide heading, subheading, and paragraph text.",
        "start_regex": r'<div[^>]+class="[^"]*\bslide slide-0 active\b[^"]*"[^>]*>',
        "tag": "div",
        "title_tag": "h1",
    },
    {
        "id": "services",
        "label": "Services",
        "description": "The Services section heading and lead paragraph.",
        "start_regex": r'<section[^>]+id="services-index"[^>]*>',
        "tag": "section",
        "title_tag": "h2",
    },
    {
        "id": "reviews",
        "label": "Reviews",
        "description": "The Reviews section heading and optional section text.",
        "start_regex": r'<section[^>]+id="reviews"[^>]*>',
        "tag": "section",
        "title_tag": "h2",
    },
    {
        "id": "contact",
        "label": "Contact us",
        "description": "The Contact section heading and optional intro paragraph.",
        "start_regex": r'<section[^>]+id="contact-index"[^>]*>',
        "tag": "section",
        "title_tag": "h2",
    },
]


def make_backup(content: str):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_DIR / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / INDEX_FILE.name
    backup_file.write_text(content, encoding="utf-8")
    return stamp


def read_index():
    return INDEX_FILE.read_text(encoding="utf-8")


def write_index(text: str):
    INDEX_FILE.write_text(text, encoding="utf-8")


def find_balanced_tag(text: str, start_pos: int, tag_name: str):
    pattern = re.compile(r"<(/?)" + re.escape(tag_name) + r"\b", re.IGNORECASE)
    count = 0
    for match in pattern.finditer(text, start_pos):
        if match.group(1) == "":
            count += 1
        else:
            count -= 1
        if count == 0:
            close = re.search(r">", text[match.end():])
            return match.end() + (close.end() if close else 0)
    return None


def find_section(html: str, slot: dict):
    match = re.search(slot["start_regex"], html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None, None
    start = match.start()
    end = find_balanced_tag(html, start, slot["tag"])
    if end is None:
        return None, None, None
    return html[start:end], start, end


def extract_tag_text(section_html: str, tag: str):
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", section_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return normalize_text(match.group(1))


def extract_paragraphs(section_html: str):
    return [normalize_text(m) for m in re.findall(r"<p[^>]*>(.*?)</p>", section_html, flags=re.IGNORECASE | re.DOTALL)]


def normalize_text(value: str):
    return re.sub(r"\s+", " ", value).strip()


def replace_tag_content(section_html: str, tag: str, new_text: str, class_name: str = None):
    if class_name:
        pattern = rf"(<{tag}[^>]*class=\"[^\"]*\b{re.escape(class_name)}\b[^\"]*\"[^>]*>)(.*?)(</{tag}>)"
    else:
        pattern = rf"(<{tag}[^>]*>)(.*?)(</{tag}>)"
    if re.search(pattern, section_html, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, rf"\1{new_text}\3", section_html, count=1, flags=re.IGNORECASE | re.DOTALL)
    return section_html


def remove_paragraph(section_html: str, index: int):
    paragraphs = list(re.finditer(r"(<p[^>]*>)(.*?)(</p>)", section_html, flags=re.IGNORECASE | re.DOTALL))
    if 1 <= index <= len(paragraphs):
        p = paragraphs[index - 1]
        return section_html[: p.start()] + section_html[p.end() :]
    return section_html


def replace_paragraph(section_html: str, index: int, new_text: str, slot_id: str):
    paragraphs = list(re.finditer(r"(<p[^>]*>)(.*?)(</p>)", section_html, flags=re.IGNORECASE | re.DOTALL))
    if 1 <= index <= len(paragraphs):
        if new_text == "":
            return remove_paragraph(section_html, index)
        p = paragraphs[index - 1]
        return section_html[: p.start()] + f"{p.group(1)}{new_text}{p.group(3)}" + section_html[p.end() :]

    if new_text == "":
        return section_html

    if slot_id == "header-slider":
        button_match = re.search(r"(<a[^>]*class=\"[^\"]*\bbtn\b[^\"]*\"[^>]*>.*?</a>)", section_html, flags=re.IGNORECASE | re.DOTALL)
        if button_match:
            insertion = f"\n               <p>{new_text}</p>"
            return section_html[: button_match.end()] + insertion + section_html[button_match.end() :]

    heading_block = re.search(
        r"(<div[^>]+class=\"[^\"]*\bsection-heading\b[^\"]*\"[^>]*>.*?</div>)",
        section_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if heading_block:
        insertion = f"\n            <p>{new_text}</p>"
        return section_html[: heading_block.end()] + insertion + section_html[heading_block.end() :]

    return section_html


def get_slot_state(slot: dict):
    html = read_index()
    section_html, _, _ = find_section(html, slot)
    if section_html is None:
        return {"id": slot["id"], "label": slot["label"], "description": slot["description"], "title": "", "subtitle": "", "body": "", "currentHtml": ""}

    paragraphs = extract_paragraphs(section_html)
    return {
        "id": slot["id"],
        "label": slot["label"],
        "description": slot["description"],
        "title": extract_tag_text(section_html, slot["title_tag"]),
        "subtitle": paragraphs[0] if len(paragraphs) >= 1 else "",
        "body": paragraphs[1] if len(paragraphs) >= 2 else "",
        "currentHtml": normalize_text(section_html),
    }


def apply_update(payload: dict):
    slot_id = payload.get("slotId")
    slot = next((s for s in SLOTS if s["id"] == slot_id), None)
    if slot is None:
        raise ValueError(f"Unknown slot: {slot_id}")

    title = payload.get("title", "")
    subtitle = payload.get("subtitle", "")
    body = payload.get("body", "")

    html = read_index()
    section_html, start, end = find_section(html, slot)
    if section_html is None:
        raise ValueError(f"Section not found for slot: {slot_id}")

    if title:
        section_html = replace_tag_content(section_html, slot["title_tag"], title)
    if subtitle != "":
        section_html = replace_paragraph(section_html, 1, subtitle, slot_id)
    if body != "":
        section_html = replace_paragraph(section_html, 2, body, slot_id)
    if subtitle == "" and body == "":
        # Do not modify paragraphs when the user leaves both blank.
        pass

    if section_html == html[start:end]:
        return {"changed": False, "message": "No changes were detected."}

    make_backup(html)
    new_html = html[:start] + section_html + html[end:]
    write_index(new_html)
    return {"changed": True, "message": "Text updated successfully."}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            self._send_json(200, {"slots": [get_slot_state(slot) for slot in SLOTS]})
            return

        request_path = self.path.split("?", 1)[0].split("#", 1)[0]
        rel = request_path.lstrip("/") or "textupdater.html"
        path = ROOT / rel
        if path.exists() and path.is_file() and path.resolve().is_relative_to(ROOT):
            self.send_response(200)
            if rel.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif rel.endswith(".js"):
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
            elif rel.endswith(".css"):
                self.send_header("Content-Type", "text/css; charset=utf-8")
            self.end_headers()
            self.wfile.write(path.read_bytes())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body)
            if self.path == "/api/update":
                result = apply_update(data)
                self._send_json(200, result)
            else:
                self._send_json(404, {"error": "Not found"})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"TextUpdater running on http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
