from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageOps


def natural_key(path: Path) -> list[Any]:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", path.name)]


def discover_presentations(source: Path) -> list[Path]:
    return sorted((p for p in source.iterdir()
                   if p.is_file() and p.suffix.lower() in {".ppt", ".pptx"}), key=natural_key)


class SlidePreprocessor:
    def __init__(self, dpi: int = 150):
        self.dpi = dpi

    def render(self, ppt: Path, deck_dir: Path, force: bool = False) -> list[Path]:
        images_dir = deck_dir / "slide_images"
        existing = sorted(images_dir.glob("slide_*.png"), key=natural_key)
        if existing and not force:
            return existing
        soffice = shutil.which("libreoffice") or shutil.which("soffice")
        if not soffice:
            raise RuntimeError("LibreOffice/soffice is not installed or not in PATH")
        images_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir = deck_dir / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(ppt)],
            capture_output=True, text=True, timeout=600)
        pdf = pdf_dir / f"{ppt.stem}.pdf"
        if process.returncode or not pdf.exists():
            raise RuntimeError(f"LibreOffice conversion failed: {process.stderr or process.stdout}")
        doc = pymupdf.open(pdf)
        scale = self.dpi / 72
        paths = []
        for index, page in enumerate(doc, 1):
            path = images_dir / f"slide_{index:04d}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(path)
            paths.append(path)
        doc.close()
        return paths

    def grids(self, images: list[Path], deck_dir: Path, force: bool = False) -> list[Path]:
        grid_dir = deck_dir / "slide_grids"
        expected = (len(images) + 3) // 4
        existing = sorted(grid_dir.glob("grid_*.jpg"), key=natural_key)
        if len(existing) == expected and not force:
            return existing
        grid_dir.mkdir(parents=True, exist_ok=True)
        for old in grid_dir.glob("grid_*.jpg"):
            old.unlink()
        output = []
        for start in range(0, len(images), 4):
            canvas = Image.new("RGB", (1620, 940), "white")
            draw = ImageDraw.Draw(canvas)
            for slot, path in enumerate(images[start:start + 4]):
                with Image.open(path) as opened:
                    slide = ImageOps.contain(opened.convert("RGB"), (800, 450))
                x, y = 10 + (slot % 2) * 805, 30 + (slot // 2) * 465
                canvas.paste(slide, (x, y))
                draw.text((x, 8 + (slot // 2) * 465), f"Slide {start + slot + 1}", fill="black")
            target = grid_dir / f"grid_{start // 4 + 1:04d}.jpg"
            canvas.save(target, quality=88, optimize=True)
            output.append(target)
        return output

