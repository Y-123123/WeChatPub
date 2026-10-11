"""Original editorial cards, not experimental data or paper figure reproductions."""
from pathlib import Path
import os

from PIL import Image, ImageDraw, ImageFont


def font(size):
    candidates = [os.getenv("IMAGE_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for name in candidates:
        if name and Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def wrap(text, draw, face, width):
    lines, current = [], ""
    for char in text:
        if char == "\n" or draw.textlength(current + char, font=face) > width:
            lines.append(current)
            current = "" if char == "\n" else char
        else:
            current += char
    return lines + ([current] if current else [])


def cards(folder, source, title):
    folder = Path(folder)
    bg, ink, accent = "#f1f5f1", "#153e36", "#328b77"
    image = Image.new("RGB", (1000, 420), ink)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((50, 45, 320, 95), radius=18, fill=accent)
    d.text((70, 53), source.get("source_label", "PubMed") + " · 文献解读", font=font(25), fill="white")
    for i, line in enumerate(wrap(title, d, font(49), 870)[:3]):
        d.text((55, 125 + i * 62), line, font=font(49), fill="white")
    d.text((55, 360), f"ID {source['pmid']}  |  {source.get('evidence_level', 'abstract_only').upper()}", font=font(24), fill="#bbd8cf")
    image.save(folder / "cover.jpg", quality=92)
    image = Image.new("RGB", (1000, 650), bg)
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 16, 650), fill=accent)
    d.text((55, 40), "论文来源 · 阅读线索", font=font(40), fill=ink)
    y = 125
    for label, value in [("TITLE", source["title"]), ("JOURNAL", source["journal"]), ("DATE / PMID", source["date"] + " / " + source["pmid"]), ("DOI", source["doi"] or "PubMed 未提供 DOI")]:
        d.text((55, y), label, font=font(20), fill=accent)
        y += 32
        for line in wrap(value, d, font(25), 880)[:3]:
            d.text((55, y), line, font=font(25), fill=ink)
            y += 34
        y += 18
    d.text((55, 596), "研究线索 · 原文入口与关键证据", font=font(23), fill=ink)
    image.save(folder / "source-card.jpg", quality=92)
