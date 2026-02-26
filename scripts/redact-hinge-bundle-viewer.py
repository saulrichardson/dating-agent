#!/usr/bin/env python3
"""
Create a public-safe redacted copy of a generated Hinge bundle HTML viewer.

Modes:
- selective (default): keep UI screenshots, redact faces/photo tiles + sensitive text regions.
- strict: replace all referenced images with neutral placeholders.

The tool writes output to a separate directory and never mutates the source bundle.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import cv2
import numpy as np


class RedactionError(RuntimeError):
    pass


SAFE_UI_EXACT = {
    "edit comment",
    "add comment",
    "send a rose",
    "send like",
    "more",
    "skip",
    "undo the previous pass rating",
    "like prompt",
    "like photo",
    "like video prompt",
    "like voice prompt",
    "age",
    "gender",
    "height",
    "location",
    "job",
    "school",
    "religion",
    "hometown",
    "dating intentions",
    "relationship type",
    "dating preferences",
    "active today",
    "active now",
    "age filter options",
    "height filter options",
    "dating intentions filter options",
    "active today filter, off",
    "active today filter, on",
    "discover",
    "standouts",
    "liked you",
    "matches",
    "chats",
    "you",
}

SAFE_UI_PREFIXES = (
    "like ",
    "send ",
    "edit comment",
    "add comment",
    "more",
    "undo",
)


@dataclass(frozen=True)
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    def clipped(self, *, w: int, h: int) -> Optional["Rect"]:
        x1 = max(0, min(self.x1, w - 1))
        y1 = max(0, min(self.y1, h - 1))
        x2 = max(0, min(self.x2, w))
        y2 = max(0, min(self.y2, h))
        if x2 <= x1 or y2 <= y1:
            return None
        return Rect(x1=x1, y1=y1, x2=x2, y2=y2)


@dataclass
class ViewMeta:
    view_index: int
    screenshot_relpath: str
    xml_relpath: str
    interaction_targets: list[dict[str, Any]]


@dataclass
class RedactionStats:
    views_processed: int = 0
    photos_masked: int = 0
    faces_masked: int = 0
    text_regions_masked: int = 0
    non_view_images_masked: int = 0


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _remove_title_attributes(html: str) -> str:
    # Titles often include names (e.g., "Skip <name>").
    return re.sub(r"\s+title=\"[^\"]*\"", "", html)


def _redact_header_meta(html: str) -> str:
    html = re.sub(
        r"(<div class=\"meta\">bundle: <span class=\"mono\">)(.*?)(</span></div>)",
        r"\1[redacted]/profile_bundle.json\3",
        html,
        count=1,
        flags=re.DOTALL,
    )
    html = re.sub(
        r"(<div class=\"meta\">profile_fingerprint: <span class=\"mono\">)(.*?)(</span></div>)",
        r"\1[redacted]\3",
        html,
        count=1,
        flags=re.DOTALL,
    )
    return html


def _redact_like_candidate_context_cells(html: str) -> str:
    row_pattern = re.compile(r"<tr>.*?</tr>", re.DOTALL)

    def _replace_row(match: re.Match[str]) -> str:
        row = match.group(0)
        if "<th>" in row:
            return row
        cells = list(re.finditer(r"<td(?:\s+[^>]*)?>.*?</td>", row, re.DOTALL))
        # Like-candidate rows have 10 columns; context_text is column index 7 (0-based).
        if len(cells) >= 8:
            s, e = cells[7].span()
            row = f"{row[:s]}<td>[redacted]</td>{row[e:]}"
        # Thumbnail cell (index 5) often exposes personal imagery.
        if len(cells) >= 6:
            cells2 = list(re.finditer(r"<td(?:\s+[^>]*)?>.*?</td>", row, re.DOTALL))
            s2, e2 = cells2[5].span()
            row = f"{row[:s2]}<td>[redacted]</td>{row[e2:]}"
        return row

    return row_pattern.sub(_replace_row, html)


def _redact_profile_summary_section(html: str) -> str:
    start_marker = '<div class="section"><div class="h2">Extracted Profile Summary (from accessibility)</div>'
    end_marker = '<div class="section"><div class="h2">Continuous Scroll (De-Overlapped)</div>'

    start = html.find(start_marker)
    end = html.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return html

    replacement = (
        '<div class="section"><div class="h2">Extracted Profile Summary (from accessibility)</div>'
        '<div class="muted">[redacted for public example]</div></div>'
    )
    return f"{html[:start]}{replacement}{html[end:]}"


def _remove_continuous_scroll_section(html: str) -> str:
    start_marker = '<div class="section"><div class="h2">Continuous Scroll (De-Overlapped)</div>'
    end_marker = '<div class="section"><div class="h2">Raw Viewports (With Overlays)</div>'
    start = html.find(start_marker)
    end = html.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return html
    replacement = (
        '<div class="section"><div class="h2">Continuous Scroll (De-Overlapped)</div>'
        '<div class="muted">[redacted for public example]</div></div>'
    )
    return f"{html[:start]}{replacement}{html[end:]}"


def sanitize_viewer_html(html: str) -> str:
    html = _remove_title_attributes(html)
    html = _redact_header_meta(html)
    html = _redact_like_candidate_context_cells(html)
    html = _redact_profile_summary_section(html)
    html = _remove_continuous_scroll_section(html)
    return html


def _extract_local_image_paths(html: str) -> list[str]:
    paths: list[str] = []
    for m in re.finditer(r"<img[^>]+src=\"([^\"]+)\"", html):
        src = m.group(1).strip()
        if not src:
            continue
        if src.startswith("http://") or src.startswith("https://") or src.startswith("data:"):
            continue
        paths.append(src)

    deduped: list[str] = []
    seen: set[str] = set()
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return deduped


def _parse_bounds(raw: str) -> Optional[Rect]:
    m = re.match(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$", str(raw or "").strip())
    if not m:
        return None
    x1, y1, x2, y2 = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1=x1, y1=y1, x2=x2, y2=y2)


def _rect_from_list(raw: Any) -> Optional[Rect]:
    if not (isinstance(raw, list) and len(raw) == 4):
        return None
    try:
        x1, y1, x2, y2 = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1=x1, y1=y1, x2=x2, y2=y2)


def _expand_rect(r: Rect, *, px: int = 0, frac: float = 0.0) -> Rect:
    w = r.x2 - r.x1
    h = r.y2 - r.y1
    ex = max(px, int(round(w * frac)))
    ey = max(px, int(round(h * frac)))
    return Rect(x1=r.x1 - ex, y1=r.y1 - ey, x2=r.x2 + ex, y2=r.y2 + ey)


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _is_safe_ui_text(s: str) -> bool:
    norm = _norm_text(s).lower()
    if not norm:
        return True
    if norm in SAFE_UI_EXACT:
        return True
    return any(norm.startswith(p) for p in SAFE_UI_PREFIXES)


def _looks_like_photo_descriptor(s: str) -> bool:
    norm = _norm_text(s).lower()
    if not norm:
        return False
    if norm in {"like photo", "photo"}:
        return False
    if "photo" in norm and ("'s" in norm or "profile" in norm or len(norm) > 12):
        return True
    return False


def _is_sensitive_text(s: str) -> bool:
    norm = _norm_text(s)
    if not norm:
        return False
    if _is_safe_ui_text(norm):
        return False
    lower = norm.lower()
    if lower.startswith("prompt:") or "answer:" in lower:
        return True
    if "@" in norm:
        return True
    if re.search(r"\b\d{1,2}\b", norm):
        return True
    # Any remaining non-empty non-safe strings are treated as profile-specific.
    return True


def _pixelate_region(img: np.ndarray, rect: Rect, *, block_px: int) -> None:
    h, w = img.shape[:2]
    rc = rect.clipped(w=w, h=h)
    if rc is None:
        return
    roi = img[rc.y1 : rc.y2, rc.x1 : rc.x2]
    rh, rw = roi.shape[:2]
    if rh < 2 or rw < 2:
        return
    down_w = max(1, rw // max(2, block_px))
    down_h = max(1, rh // max(2, block_px))
    small = cv2.resize(roi, (down_w, down_h), interpolation=cv2.INTER_LINEAR)
    pix = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
    img[rc.y1 : rc.y2, rc.x1 : rc.x2] = pix


def _blur_dark_region(img: np.ndarray, rect: Rect) -> None:
    h, w = img.shape[:2]
    rc = rect.clipped(w=w, h=h)
    if rc is None:
        return
    roi = img[rc.y1 : rc.y2, rc.x1 : rc.x2]
    rh, rw = roi.shape[:2]
    if rh < 2 or rw < 2:
        return
    blur = cv2.GaussianBlur(roi, ksize=(0, 0), sigmaX=7.0, sigmaY=7.0)
    dark = np.full_like(blur, 20)
    mixed = cv2.addWeighted(blur, 0.72, dark, 0.28, 0)
    img[rc.y1 : rc.y2, rc.x1 : rc.x2] = mixed


def _blackout_region(img: np.ndarray, rect: Rect) -> None:
    h, w = img.shape[:2]
    rc = rect.clipped(w=w, h=h)
    if rc is None:
        return
    img[rc.y1 : rc.y2, rc.x1 : rc.x2] = 0


def _load_bundle_views(bundle_json_path: Path) -> dict[str, ViewMeta]:
    raw = json.loads(bundle_json_path.read_text(encoding="utf-8"))
    views = raw.get("views")
    if not isinstance(views, list):
        raise RedactionError(f"bundle json missing views[]: {bundle_json_path}")

    by_rel: dict[str, ViewMeta] = {}
    for v in views:
        if not isinstance(v, dict):
            continue
        vi = int(v.get("view_index") or 0)
        screenshot_rel = str(v.get("screenshot_relpath") or "").strip()
        xml_rel = str(v.get("xml_relpath") or "").strip()
        if not screenshot_rel:
            shot_path_raw = str(v.get("screenshot_path") or "").strip()
            if shot_path_raw:
                screenshot_rel = Path(shot_path_raw).name
        if not xml_rel:
            xml_path_raw = str(v.get("xml_path") or "").strip()
            if xml_path_raw:
                xml_rel = Path(xml_path_raw).name
        if not screenshot_rel:
            continue

        meta = ViewMeta(
            view_index=vi,
            screenshot_relpath=Path(screenshot_rel).as_posix(),
            xml_relpath=Path(xml_rel).as_posix() if xml_rel else "",
            interaction_targets=[x for x in (v.get("interaction_targets") or []) if isinstance(x, dict)],
        )
        by_rel[meta.screenshot_relpath] = meta

    return by_rel


def _find_view_meta_for_image(rel_img_path: str, by_rel: dict[str, ViewMeta]) -> Optional[ViewMeta]:
    rel_norm = Path(rel_img_path).as_posix()
    if rel_norm in by_rel:
        return by_rel[rel_norm]
    name = Path(rel_norm).name
    candidates = [v for k, v in by_rel.items() if Path(k).name == name]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _collect_sensitive_regions(*, bundle_dir: Path, view: ViewMeta) -> tuple[list[Rect], list[Rect]]:
    photo_rects: list[Rect] = []
    text_rects: list[Rect] = []

    # 1) Use interaction targets to locate photo tile geometry.
    for t in view.interaction_targets:
        kind = str(t.get("kind") or "")
        label = _norm_text(str(t.get("label") or ""))

        if kind == "like_button" and "photo" in label.lower():
            tb = _rect_from_list(t.get("tile_bounds"))
            if tb is not None:
                photo_rects.append(_expand_rect(tb, frac=0.03))
            b = _rect_from_list(t.get("bounds"))
            if b is not None:
                photo_rects.append(_expand_rect(b, px=4))

        # If context_text attached to a target includes profile copy, hide that region.
        ctx = t.get("context_text")
        if isinstance(ctx, list):
            if any(isinstance(x, str) and _is_sensitive_text(x) for x in ctx):
                b = _rect_from_list(t.get("bounds"))
                if b is not None:
                    text_rects.append(_expand_rect(b, px=5))

        # Labels like "Skip <name>" should be treated as sensitive text.
        if label and _is_sensitive_text(label):
            b = _rect_from_list(t.get("bounds"))
            if b is not None:
                text_rects.append(_expand_rect(b, px=5))

    # 2) Use raw XML nodes for text/photo descriptors.
    if view.xml_relpath:
        xml_path = (bundle_dir / view.xml_relpath).resolve()
        if xml_path.exists():
            xml_text = xml_path.read_text(encoding="utf-8")
            root = ET.fromstring(xml_text)
            for el in root.iter():
                bounds = _parse_bounds(str(el.attrib.get("bounds") or ""))
                if bounds is None:
                    continue

                txt = _norm_text(str(el.attrib.get("text") or ""))
                desc = _norm_text(str(el.attrib.get("content-desc") or ""))
                candidates = [s for s in (txt, desc) if s]
                if not candidates:
                    continue

                if any(_looks_like_photo_descriptor(s) for s in candidates):
                    photo_rects.append(_expand_rect(bounds, frac=0.04))
                    continue

                if any(_is_sensitive_text(s) for s in candidates):
                    text_rects.append(_expand_rect(bounds, px=4))

    # Deduplicate exact rectangles.
    photo_rects = list({(r.x1, r.y1, r.x2, r.y2): r for r in photo_rects}.values())
    text_rects = list({(r.x1, r.y1, r.x2, r.y2): r for r in text_rects}.values())
    return photo_rects, text_rects


def _detect_face_regions(img: np.ndarray) -> list[Rect]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    classifier = cv2.CascadeClassifier(cascade_path)
    if classifier.empty():
        return []

    faces = classifier.detectMultiScale(
        gray,
        scaleFactor=1.10,
        minNeighbors=5,
        minSize=(44, 44),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    out: list[Rect] = []
    for x, y, w, h in faces:
        r = Rect(int(x), int(y), int(x + w), int(y + h))
        out.append(_expand_rect(r, frac=0.25, px=6))
    return out


def _redact_view_image_selective(*, src_img: Path, dst_img: Path, bundle_dir: Path, view: ViewMeta, stats: RedactionStats) -> None:
    img = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
    if img is None:
        raise RedactionError(f"Could not read image: {src_img}")

    photo_rects, text_rects = _collect_sensitive_regions(bundle_dir=bundle_dir, view=view)
    face_rects = _detect_face_regions(img)

    # Strong selective mode: redact identified sensitive regions as solid black boxes.
    for r in photo_rects:
        _blackout_region(img, r)
    for r in face_rects:
        _blackout_region(img, r)
    for r in text_rects:
        _blackout_region(img, r)

    dst_img.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(dst_img), img)
    if not ok:
        raise RedactionError(f"Could not write redacted image: {dst_img}")

    stats.views_processed += 1
    stats.photos_masked += len(photo_rects)
    stats.faces_masked += len(face_rects)
    stats.text_regions_masked += len(text_rects)


def _redact_image_strict(*, src_img: Path, dst_img: Path) -> None:
    img = cv2.imread(str(src_img), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RedactionError(f"Could not read image: {src_img}")
    h, w = img.shape[:2]
    ch = 1 if len(img.shape) == 2 else img.shape[2]

    if ch == 1:
        out = np.full((h, w), 26, dtype=np.uint8)
    elif ch == 3:
        out = np.full((h, w, 3), (26, 30, 37), dtype=np.uint8)
    else:
        out = np.full((h, w, ch), (26, 30, 37, 255), dtype=np.uint8)

    dst_img.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(dst_img), out)
    if not ok:
        raise RedactionError(f"Could not write strict redacted image: {dst_img}")


def _pixelate_full_image(*, src_img: Path, dst_img: Path) -> None:
    img = cv2.imread(str(src_img), cv2.IMREAD_COLOR)
    if img is None:
        raise RedactionError(f"Could not read image: {src_img}")
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // 32), max(1, h // 32)), interpolation=cv2.INTER_LINEAR)
    out = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    dst_img.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(dst_img), out)
    if not ok:
        raise RedactionError(f"Could not write pixelated image: {dst_img}")


def _write_readme(out_dir: Path, *, mode: str, image_count: int, stats: RedactionStats) -> None:
    lines = [
        "This folder is a redacted copy of a Hinge bundle viewer for public sharing.",
        "",
        f"mode: {mode}",
        f"images_processed: {image_count}",
    ]
    if mode == "selective":
        lines.extend(
            [
                f"views_processed: {stats.views_processed}",
                f"photo_regions_masked: {stats.photos_masked}",
                f"face_regions_masked: {stats.faces_masked}",
                f"text_regions_masked: {stats.text_regions_masked}",
                f"non_view_images_masked: {stats.non_view_images_masked}",
                "",
                "Strategy:",
                "- Keep viewport structure visible",
                "- Black out photo/facial regions",
                "- Black out sensitive text regions from XML bounds",
            ]
        )
    else:
        lines.extend(["", "Strategy:", "- Replace all referenced images with neutral placeholders"])

    lines.extend(
        [
            "",
            "HTML redactions:",
            "- Removed tooltip title attributes",
            "- Redacted profile summary block",
            "- Redacted like-candidate context text",
            "- Removed continuous-scroll content block",
        ]
    )

    _write_text(out_dir / "README.txt", "\n".join(lines) + "\n")


def _assert_not_same_path(src: Path, out: Path) -> None:
    if src.resolve() == out.resolve():
        raise RedactionError("Output directory must be different from source bundle directory")


def run(*, src_bundle_dir: Path, out_dir: Path, mode: str) -> tuple[Path, RedactionStats, int]:
    viewer_src = src_bundle_dir / "bundle_viewer.html"
    if not viewer_src.exists():
        raise RedactionError(f"bundle_viewer.html not found: {viewer_src}")

    _assert_not_same_path(src_bundle_dir, out_dir)

    html_in = _read_text(viewer_src)
    html_out = sanitize_viewer_html(html_in)
    image_paths = _extract_local_image_paths(html_out)

    bundle_json_path = src_bundle_dir / "profile_bundle.json"
    by_rel: dict[str, ViewMeta] = {}
    if mode == "selective":
        if bundle_json_path.exists():
            by_rel = _load_bundle_views(bundle_json_path)
        else:
            raise RedactionError(f"profile_bundle.json required for selective mode: {bundle_json_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    viewer_out = out_dir / "bundle_viewer.html"
    _write_text(viewer_out, html_out)

    stats = RedactionStats()

    for rel in image_paths:
        src_img = (src_bundle_dir / rel).resolve()
        dst_img = (out_dir / rel).resolve()
        if not src_img.exists():
            raise RedactionError(f"Referenced image does not exist: {src_img}")

        if mode == "strict":
            _redact_image_strict(src_img=src_img, dst_img=dst_img)
            continue

        view_meta = _find_view_meta_for_image(rel, by_rel)
        if view_meta is not None:
            _redact_view_image_selective(
                src_img=src_img,
                dst_img=dst_img,
                bundle_dir=src_bundle_dir,
                view=view_meta,
                stats=stats,
            )
        else:
            _pixelate_full_image(src_img=src_img, dst_img=dst_img)
            stats.non_view_images_masked += 1

    _write_readme(out_dir=out_dir, mode=mode, image_count=len(image_paths), stats=stats)
    return viewer_out, stats, len(image_paths)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Create a public-safe redacted copy of a generated hinge bundle viewer. "
            "By default writes to <bundle-dir>/public_redacted_selective/."
        )
    )
    p.add_argument("--bundle-dir", required=True, help="Source bundle directory containing bundle_viewer.html")
    p.add_argument("--out-dir", default="", help="Output directory")
    p.add_argument(
        "--mode",
        choices=["selective", "strict"],
        default="selective",
        help="Redaction mode. selective keeps UI and masks sensitive regions; strict replaces images entirely.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    src_bundle_dir = Path(args.bundle_dir).expanduser().resolve()
    if not src_bundle_dir.exists() or not src_bundle_dir.is_dir():
        raise SystemExit(f"ERROR: bundle dir does not exist or is not a directory: {src_bundle_dir}")

    if str(args.out_dir or "").strip():
        out_dir = Path(args.out_dir).expanduser().resolve()
    else:
        suffix = "public_redacted_selective" if args.mode == "selective" else "public_redacted_strict"
        out_dir = (src_bundle_dir / suffix).resolve()

    try:
        viewer_out, stats, image_count = run(src_bundle_dir=src_bundle_dir, out_dir=out_dir, mode=args.mode)
    except RedactionError as e:
        raise SystemExit(f"ERROR: {e}") from e

    print(str(viewer_out))
    print(
        json.dumps(
            {
                "mode": args.mode,
                "images_processed": image_count,
                "views_processed": stats.views_processed,
                "photos_masked": stats.photos_masked,
                "faces_masked": stats.faces_masked,
                "text_regions_masked": stats.text_regions_masked,
                "non_view_images_masked": stats.non_view_images_masked,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
