"""
Content analysis stage. Produces:
  - content-inventory.json: every page's headings, paragraphs, links, images, CTAs
  - information-architecture.json: site tree clustered by URL path

The goal: enough structure that a rebuilder knows what content needs to be
replaced and where it sits in the IA, without dragging in styling concerns.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scripts.config import Config
from scripts.models import (
    CaptureManifest,
    ContentCTA,
    ContentImage,
    ContentInventory,
    ContentLink,
    ContentSection,
    IANode,
    IATree,
    PageContent,
    PageMeta,
    load_model,
    write_model,
)
from scripts.utils import ensure_dir


log = logging.getLogger(__name__)


def run(config: Config, captures: CaptureManifest) -> tuple[ContentInventory, IATree]:
    analysis_dir = ensure_dir(config.output_dir / "analysis")

    pages: dict[str, PageContent] = {}
    for cap in captures.captures:
        if cap.status != "ok":
            continue
        rendered = (config.output_dir / cap.files.rendered_html).read_text(errors="ignore")
        meta = load_model(config.output_dir / cap.files.meta, PageMeta)
        pages[cap.slug] = _inventory_page(cap.url, rendered, meta)

    inv = ContentInventory(pages=pages)
    write_model(analysis_dir / "content-inventory.json", inv)

    ia = _build_ia(captures, pages)
    write_model(analysis_dir / "information-architecture.json", ia)
    return inv, ia


def _inventory_page(url: str, html: str, meta: PageMeta) -> PageContent:
    soup = BeautifulSoup(html, "lxml")
    sections: list[ContentSection] = []

    # Strategy: find every <section>, <article>, or <main> + heading-rooted chunks
    containers = soup.find_all(["section", "article", "main"])
    if not containers:
        containers = [soup.body] if soup.body else []

    seen_ids: set[int] = set()
    for c in containers:
        if id(c) in seen_ids:
            continue
        seen_ids.add(id(c))
        section = _inventory_container(c, url)
        if section.heading or section.paragraphs:
            sections.append(section)

    # If the body has free-floating headings that didn't end up in any container,
    # capture them as flat sections
    if soup.body and not sections:
        sections.append(_inventory_container(soup.body, url))

    return PageContent(
        url=url,
        title=meta.title,
        description=meta.description,
        sections=sections,
    )


def _inventory_container(container, page_url: str) -> ContentSection:
    heading = None
    level = None
    for h in ("h1", "h2", "h3", "h4"):
        tag = container.find(h)
        if tag:
            heading = tag.get_text(strip=True)
            level = int(h[1])
            break

    paragraphs: list[str] = []
    for p in container.find_all("p"):
        text = p.get_text(strip=True)
        if text and len(text) > 5:
            paragraphs.append(text)

    links: list[ContentLink] = []
    for a in container.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text:
            links.append(ContentLink(text=text, href=urljoin(page_url, a["href"])))

    images: list[ContentImage] = []
    for img in container.find_all("img"):
        src = img.get("src")
        if src:
            caption_tag = img.find_parent("figure").find("figcaption") if img.find_parent("figure") else None
            images.append(ContentImage(
                src=urljoin(page_url, src),
                alt=img.get("alt", ""),
                caption=caption_tag.get_text(strip=True) if caption_tag else None,
            ))

    ctas: list[ContentCTA] = []
    for el in container.find_all(["button", "a"]):
        classes = " ".join(el.get("class") or []).lower()
        if el.name == "button" or "btn" in classes or "cta" in classes or "button" in classes:
            text = el.get_text(strip=True)
            if text:
                kind = "button" if el.name == "button" else "link"
                href = el.get("href")
                ctas.append(ContentCTA(
                    text=text,
                    href=urljoin(page_url, href) if href else None,
                    kind=kind,
                ))

    section_id = container.get("id")
    return ContentSection(
        id=section_id,
        heading=heading,
        level=level,
        paragraphs=paragraphs,
        links=links,
        images=images,
        ctas=ctas,
    )


def _build_ia(captures: CaptureManifest, pages: dict[str, PageContent]) -> IATree:
    """
    Build an IA tree by URL path prefix.

    Algorithm: take every URL's path, split on /, and nest under common prefixes.
    """
    root = IANode(slug="root", url="/", title="(root)", depth=0, children=[])
    by_path: dict[tuple[str, ...], IANode] = {tuple(): root}

    sorted_pages = sorted(captures.captures, key=lambda c: c.url)
    for cap in sorted_pages:
        if cap.status != "ok":
            continue
        path = urlparse(cap.url).path.strip("/")
        parts = tuple(path.split("/")) if path else tuple()
        title = pages[cap.slug].title if cap.slug in pages else cap.slug

        # Walk/create nodes
        current = root
        for i, part in enumerate(parts):
            key = parts[: i + 1]
            if key in by_path:
                current = by_path[key]
                continue
            new_node = IANode(
                slug=cap.slug if key == parts else "__".join(key),
                url="/" + "/".join(key),
                title=title if key == parts else part,
                depth=i + 1,
                children=[],
            )
            current.children.append(new_node)
            by_path[key] = new_node
            current = new_node

    return IATree(root=root)
