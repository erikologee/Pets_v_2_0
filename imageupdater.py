#!/usr/bin/env python3
import base64
import json
import mimetypes
import os
import re
import shutil
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import struct
from typing import Optional

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "imageupdater.config.json"
BACKUP_DIR = ROOT / ".imageupdater-backups"
PORT = int(os.environ.get("PORT", "5599"))
MAX_BODY = 60 * 1024 * 1024
ALLOWED_IMAGE_EXT = [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"]

# Try to import Pillow for robust image handling; fall back to header parsing when unavailable.
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    Image = None
    PIL_AVAILABLE = False

class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status

# ----------------------------------------------------------------- Helpers

def read_config():
    if not CONFIG_FILE.is_file():
        return {"imageDir": "img/CustomImage", "scan": ["index.html", "css/*.css"], "groups": []}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

def write_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=3, ensure_ascii=False) + "\n", encoding="utf-8")

def inside_root(path: Path) -> bool:
    try:
        resolved = path.resolve() if path.exists() else (path.parent.resolve() / path.name)
    except OSError: return False
    return ROOT in resolved.parents

def list_backups():
    if not BACKUP_DIR.is_dir(): return []
    return sorted([e.name for e in BACKUP_DIR.iterdir() if e.is_dir()], reverse=True)


def _size_from_png(fobj) -> Optional[tuple]:
    # PNG: IHDR chunk contains width/height in bytes 16..24
    try:
        sig = fobj.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            return None
        # read chunks until IHDR
        length = struct.unpack('>I', fobj.read(4))[0]
        ctype = fobj.read(4)
        if ctype != b'IHDR':
            return None
        data = fobj.read(8)
        width, height = struct.unpack('>II', data)
        return width, height
    except Exception:
        return None


def _size_from_gif(fobj) -> Optional[tuple]:
    try:
        header = fobj.read(10)
        if header[:6] not in (b'GIF87a', b'GIF89a'):
            return None
        width, height = struct.unpack('<HH', header[6:10])
        return width, height
    except Exception:
        return None


def _size_from_jpeg(fobj) -> Optional[tuple]:
    # Minimal JPEG SOF parser
    try:
        data = fobj.read()
        i = 0
        if data[0] != 0xFF or data[1] != 0xD8:
            return None
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i+1]
            i += 2
            if marker == 0xDA:  # start of scan
                break
            length = struct.unpack('>H', data[i:i+2])[0]
            if 0xC0 <= marker <= 0xC3 or 0xC5 <= marker <= 0xC7 or 0xC9 <= marker <= 0xCB or 0xCD <= marker <= 0xCF:
                # SOF markers
                h = struct.unpack('>H', data[i+3:i+5])[0]
                w = struct.unpack('>H', data[i+5:i+7])[0]
                return w, h
            i += length
        return None
    except Exception:
        return None


def get_image_dimensions(path: Path) -> Optional[tuple]:
    """Return (width, height) for common image formats.

    Uses Pillow when available, otherwise parses headers for PNG, GIF, JPEG.
    """
    try:
        if PIL_AVAILABLE:
            with Image.open(path) as im:
                return im.width, im.height
        else:
            with path.open('rb') as f:
                sig = f.read(12)
                f.seek(0)
                if sig.startswith(b'\x89PNG'):
                    return _size_from_png(f)
                if sig[:6] in (b'GIF87a', b'GIF89a'):
                    return _size_from_gif(f)
                if sig[0:2] == b'\xff\xd8':
                    return _size_from_jpeg(f)
                # WebP and SVG and other formats are not reliably parsed here
    except Exception:
        return None
    return None


def create_thumbnail(src: Path, dest: Path, size=(200, 200)) -> bool:
    """Create a thumbnail at `dest`. Returns True on success.

    If Pillow is not available, this is a no-op and returns False.
    """
    try:
        if not PIL_AVAILABLE:
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.thumbnail(size, Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.ANTIALIAS)
            # Maintain format if possible
            fmt = im.format or 'PNG'
            im.save(dest, format=fmt)
        return True
    except Exception:
        return False


def parse_css_size(selector: str, files: list) -> Optional[tuple]:
    """Search CSS files for selector block and parse width/height or background-size (px).

    Returns (width, height) in pixels or None.
    """
    sel_pattern = re.escape(selector).replace(r'\ ', r'\s+')
    for rel in files:
        if not rel.endswith('.css'): continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:
            continue
        for m in re.finditer(sel_pattern + r'\s*\{', text):
            block, start, end = get_balanced_block(text, m.end())
            if block is None: continue
            # find declarations
            w = None
            h = None
            bg_size = None
            for decl in re.findall(r'([a-zA-Z\-]+)\s*:\s*([^;]+);', block):
                prop, val = decl[0].strip(), decl[1].strip()
                if prop == 'width' and val.endswith('px'):
                    try: w = int(re.match(r'(\d+)', val).group(1))
                    except: pass
                if prop == 'height' and val.endswith('px'):
                    try: h = int(re.match(r'(\d+)', val).group(1))
                    except: pass
                if prop == 'background-size':
                    bg_size = val
            if bg_size:
                # parse '123px 456px' or '123px'
                parts = bg_size.split()
                if len(parts) == 2 and parts[0].endswith('px') and parts[1].endswith('px'):
                    try:
                        w = int(re.match(r'(\d+)', parts[0]).group(1))
                        h = int(re.match(r'(\d+)', parts[1]).group(1))
                    except: pass
            if w or h:
                return (w or None, h or None)
    return None

def scanned_files(config, patterns=None):
    files = []
    scan_list = patterns if patterns is not None else config.get("scan", [])
    for pattern in scan_list:
        if "*" in pattern:
            directory, _, suffix = pattern.rpartition("*")
            abs_dir = ROOT / directory.rstrip("/")
            if abs_dir.is_dir():
                for e in abs_dir.iterdir():
                    if e.is_file() and e.name.endswith(suffix):
                        rel = e.relative_to(ROOT).as_posix()
                        if rel not in files: files.append(rel)
        else:
            if (ROOT / pattern).is_file():
                if pattern not in files: files.append(pattern)
    return [f for f in files if f not in ("imageupdater.html", "imageupdater.py")]

def get_balanced_block(text, start_index):
    brace_level = 0
    first_brace = text.find("{", start_index)
    if first_brace == -1: return None, -1, -1
    for i in range(first_brace, len(text)):
        if text[i] == "{": brace_level += 1
        elif text[i] == "}":
            brace_level -= 1
            if brace_level == 0: return text[first_brace+1:i], first_brace, i
    return None, -1, -1

def replace_ref(text, slot, new_ref, rel):
    old_ref = slot["ref"]
    is_css = rel.endswith(".css")
    targets = [old_ref]
    if is_css and not old_ref.startswith(".."): targets.append("../" + old_ref)
    elif not is_css and old_ref.startswith("../"): targets.append(old_ref[3:])

    def _normalize_ref(value):
        if not value:
            return ""
        value = value.split("#", 1)[0].split("?", 1)[0]
        if value.startswith("./"):
            return value[2:]
        return value

    targets_norm = {_normalize_ref(t) for t in targets if t}
    hits = 0
    selector = slot.get("cssRule")

    if not is_css:
        attr_pattern = re.compile(
            r"(?P<attr>\b(?:src|href|poster|data-src|data-srcset|srcset|data-lazy-src|data-lazy-srcset|data-bg)\b)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
            re.IGNORECASE,
        )
        style_pattern = re.compile(r"(?P<attr>\bstyle\b)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.IGNORECASE | re.DOTALL)
        url_pattern = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<value>[^'\"\)]+)(?P=quote)\s*\)", re.IGNORECASE)
        bg_pattern = re.compile(r"(background-image\s*:\s*url\(\s*['\"]?)([^'\"\)]+)(['\"]?\s*\))", re.IGNORECASE)

        def _replace_attr(match):
            nonlocal hits
            attr_name = match.group("attr").lower()
            value = match.group("value")

            if attr_name in {"srcset", "data-srcset", "data-lazy-srcset"}:
                parts = []
                changed = False
                for raw_part in value.split(","):
                    part = raw_part.strip()
                    if not part:
                        continue
                    tokens = part.split()
                    if tokens:
                        first = tokens[0]
                        if _normalize_ref(first) in targets_norm:
                            changed = True
                            tokens[0] = new_ref
                    parts.append(" ".join(tokens))
                if changed:
                    hits += 1
                    return f"{attr_name}={match.group('quote')}{','.join(parts)}{match.group('quote')}"
                return match.group(0)

            normalized = _normalize_ref(value)
            if normalized in targets_norm:
                hits += 1
                return f"{attr_name}={match.group('quote')}{new_ref}{match.group('quote')}"
            return match.group(0)

        def _replace_style(match):
            nonlocal hits
            raw_value = match.group("value")

            def _replace_url(inner):
                nonlocal hits
                normalized = _normalize_ref(inner.group("value"))
                if normalized in targets_norm:
                    hits += 1
                    return f"url({inner.group('quote')}{new_ref}{inner.group('quote')})"
                return inner.group(0)

            updated_value = url_pattern.sub(_replace_url, raw_value)
            if updated_value != raw_value:
                return f"style={match.group('quote')}{updated_value}{match.group('quote')}"
            return match.group(0)

        def _replace_bg(match):
            nonlocal hits
            raw = _normalize_ref(match.group(2))
            if raw in targets_norm:
                hits += 1
                return match.group(1) + new_ref + match.group(3)
            return match.group(0)

        text = attr_pattern.sub(_replace_attr, text)
        text = style_pattern.sub(_replace_style, text)
        text = bg_pattern.sub(_replace_bg, text)
        if hits:
            return text, hits

    if not selector or not is_css:
        new_text = text
        for t in targets:
            actual_new = ("../" + new_ref) if (is_css and t.startswith("../")) else new_ref
            hits += new_text.count(t)
            new_text = new_text.replace(t, actual_new)
        return new_text, hits

    output, last_pos = [], 0
    sel_pattern = re.escape(selector).replace(r'\ ', r'\s+')
    for m in re.finditer(sel_pattern, text):
        output.append(text[last_pos:m.start()])
        block_content, block_start, block_end = get_balanced_block(text, m.end())
        if block_content:
            updated_block = block_content
            for t in targets:
                actual_new = ("../" + new_ref) if t.startswith("../") else new_ref
                hits += updated_block.count(t)
                updated_block = updated_block.replace(t, actual_new)
            output.append(text[m.start():block_start+1])
            output.append(updated_block)
            last_pos = block_end
        else:
            output.append(text[m.start():m.end()])
            last_pos = m.end()
    output.append(text[last_pos:])
    return "".join(output), hits

def cleanup_old_images(old_ref):
    if not old_ref: return
    old_path = ROOT / old_ref
    if inside_root(old_path) and old_path.is_file():
        try: os.remove(old_path)
        except: pass

# ------------------------------------------------------------- Logic

def apply_updates(payload):
    items = payload.get("updates") or []
    config = read_config()
    prepared, seen_slots = [], set()

    for item in items:
        slot_id = item.get("slotId")
        slot_found = None
        for g in config["groups"]:
            for s in g["slots"]:
                if s["id"] == slot_id:
                    slot_found = (g, s)
                    break
        if not slot_found or slot_id in seen_slots: continue
        seen_slots.add(slot_id)
        ext = os.path.splitext(item.get("fileName", ""))[1].lower()
        data = base64.b64decode(item.get("dataBase64") or "")
        prepared.append({"group": slot_found[0], "slot": slot_found[1], "ext": ext, "data": data})

    image_dir = ROOT / config["imageDir"]
    image_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_DIR / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CONFIG_FILE, backup_dir / CONFIG_FILE.name)

    results, replacements, changed_files = [], [], []
    for p in prepared:
        slot = p["slot"]
        target_name = f"{slot['id']}-{stamp}{p['ext']}"
        target_abs = image_dir / target_name
        target_abs.write_bytes(p["data"])
        # If Pillow is available and group defines a target size (or CSS rule defines it), resize the image
        target_size = None
        try:
            group = p.get('group') or {}
            # prefer css-rule size if provided
            css_rule = slot.get('cssRule') or group.get('cssRule')
            files = scanned_files(config)
            if css_rule:
                css_size = parse_css_size(css_rule, files)
                if css_size and any(css_size):
                    target_size = css_size
            if not target_size:
                # fallback to group width/height from config
                gw = group.get('width')
                gh = group.get('height')
                if gw or gh:
                    target_size = (gw or None, gh or None)
            if PIL_AVAILABLE and target_size and (target_size[0] or target_size[1]):
                try:
                    with Image.open(target_abs) as im:
                        tw = target_size[0] or im.width
                        th = target_size[1] or im.height
                        # center-crop to cover then resize
                        src_ratio = im.width / im.height
                        dst_ratio = tw / th if th else src_ratio
                        if src_ratio > dst_ratio:
                            # source wider -> crop sides
                            new_w = int(im.height * dst_ratio)
                            left = (im.width - new_w) // 2
                            im = im.crop((left, 0, left + new_w, im.height))
                        else:
                            # source taller -> crop top/bottom
                            new_h = int(im.width / dst_ratio) if dst_ratio else im.height
                            top = (im.height - new_h) // 2
                            im = im.crop((0, top, im.width, top + new_h))
                        im = im.resize((int(tw), int(th)), Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.ANTIALIAS)
                        im.save(target_abs)
                except Exception:
                    pass
        except Exception:
            pass
        new_ref = target_abs.relative_to(ROOT).as_posix()
        replacements.append((slot, slot["ref"], new_ref))
        results.append({"slot": slot["id"], "label": slot["label"], "previousRef": slot["ref"], "newFile": new_ref, "replaced": 0})

    all_files = scanned_files(config)
    for rel in all_files:
        abs_path = ROOT / rel
        original_text = abs_path.read_text(encoding="utf-8")
        text, file_hits = original_text, 0
        for i, (slot, old_ref, new_ref) in enumerate(replacements):
            text, count = replace_ref(text, slot, new_ref, rel)
            results[i]["replaced"] += count
            file_hits += count
        if text != original_text:
            (backup_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (backup_dir / rel).write_text(original_text, encoding="utf-8")
            abs_path.write_text(text, encoding="utf-8")
            changed_files.append({"file": rel, "count": file_hits})

    for slot, old_ref, new_ref in replacements:
        slot["ref"] = new_ref
        cleanup_old_images(old_ref)
    write_config(config)
    return {"results": results, "changedFiles": changed_files, "backup": stamp, "warnings": []}

# ----------------------------------------------------------------- Server

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            config = read_config()
            files = scanned_files(config)
            usages = {}
            for g in config["groups"]:
                for s in g["slots"]:
                    hits = []
                    for rel in files:
                        txt = (ROOT / rel).read_text(encoding="utf-8")
                        _, count = replace_ref(txt, s, "dummy", rel)
                        if count > 0: hits.append({"file": rel, "count": count})
                    usages[s["id"]] = hits
            # Augment group/slot data with image metadata and (optional) thumbnails.
            image_dir = ROOT / config.get("imageDir", "img/CustomImage")
            thumbs_dir = image_dir / ".thumbs"
            thumb_cache = {}
            file_info_cache = {}

            def _file_info(relpath):
                if relpath in file_info_cache:
                    return file_info_cache[relpath]
                abs_path = ROOT / relpath
                info = {"exists": False, "width": None, "height": None, "size": None}
                try:
                    if abs_path.is_file() and inside_root(abs_path):
                        info["exists"] = True
                        dims = get_image_dimensions(abs_path)
                        if dims:
                            info["width"], info["height"] = dims
                        info["size"] = abs_path.stat().st_size
                except Exception:
                    pass
                file_info_cache[relpath] = info
                return info

            groups_out = []
            for g in config.get("groups", []):
                gcopy = dict(g)
                slots_out = []
                for s in gcopy.get("slots", []):
                    ref = s.get("ref")
                    # Normalize relative path - don't resolve external refs
                    relref = ref
                    # If ref starts with ../ and file exists in that form on disk, keep it
                    if relref.startswith("../"):
                        # convert to path relative to ROOT if possible
                        cand = (ROOT / relref).resolve()
                        try:
                            relref = cand.relative_to(ROOT).as_posix()
                        except Exception:
                            relref = ref

                    info = _file_info(relref)

                    thumb_rel = None
                    if info.get("exists"):
                        src_abs = ROOT / relref
                        # determine thumb path
                        ext = Path(relref).suffix or ".jpg"
                        thumb_name = f"{s.get('id')}-thumb{ext}"
                        thumb_abs = thumbs_dir / thumb_name
                        # Create thumbnail if possible and needed
                        try:
                            if not thumb_abs.exists() or thumb_abs.stat().st_mtime < src_abs.stat().st_mtime:
                                created = create_thumbnail(src_abs, thumb_abs)
                                if not created and thumb_abs.exists():
                                    # leave existing
                                    pass
                            if thumb_abs.exists():
                                thumb_rel = thumb_abs.relative_to(ROOT).as_posix()
                        except Exception:
                            thumb_rel = None

                    slot_out = dict(s)
                    slot_out["currentRef"] = relref
                    slot_out["title"] = s.get("label") or gcopy.get("label")
                    slot_out.update(info)
                    slot_out["thumb"] = thumb_rel or ref
                    slots_out.append(slot_out)
                gcopy["slots"] = slots_out
                groups_out.append(gcopy)

            self._send_json(200, {
                "imageDir": config.get("imageDir", "img/CustomImage"),
                "groups": groups_out,
                "usages": usages,
                "scannedFiles": files,
                "backups": list_backups()
            })
        else:
            # strip query string and fragment to allow cache-busting params (?t=...) to work
            request_path = self.path.split('?', 1)[0].split('#', 1)[0]
            rel = request_path.lstrip("/") or "imageupdater.html"
            path = ROOT / rel
            if inside_root(path) and path.is_file():
                self.send_response(200)
                # Set mime type for images
                mime, _ = mimetypes.guess_type(str(path))
                if mime: self.send_header("Content-Type", mime)
                self.end_headers()
                try:
                    print(f"Serving file: {path}")
                except Exception:
                    pass
                self.wfile.write(path.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/update":
                self._send_json(200, apply_updates(data))
            elif self.path == "/api/restore":
                stamp = data.get("stamp")
                dir_abs = BACKUP_DIR / stamp
                restored = []
                for p in dir_abs.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(dir_abs)
                        shutil.copyfile(p, ROOT / rel)
                        restored.append(rel.as_posix())
                self._send_json(200, {"restored": restored})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"ImageUpdater running on http://localhost:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    main()