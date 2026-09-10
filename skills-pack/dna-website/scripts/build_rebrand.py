"""
Build the rebrand layer. Produces:
  - rebrand/tokens.original.json     — copy of the extracted tokens
  - rebrand/tokens.template.json     — same tokens with placeholders
  - rebrand/content.original.json    — copy of the content inventory
  - rebrand/content.template.json    — same content with placeholders
  - rebrand/swap-map.json            — original → placeholder map
  - rebrand/README.md                — instructions for the user

The placeholders use Mustache-style braces ({{NAME}}) so they survive any
templating engine the user later wants to swap them into.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from scripts.config import Config
from scripts.models import (
    ContentInventory,
    DesignTokens,
    SwapMap,
    SwapMapMeta,
    write_model,
)
from scripts.utils import ensure_dir


log = logging.getLogger(__name__)

PLACEHOLDER_TOKENS = {
    # color
    "brand.primary":   "{{BRAND_PRIMARY}}",
    "brand.secondary": "{{BRAND_SECONDARY}}",
    "accent.success":  "{{ACCENT_SUCCESS}}",
    "accent.warning":  "{{ACCENT_WARNING}}",
    "accent.danger":   "{{ACCENT_DANGER}}",
    "accent.info":     "{{ACCENT_INFO}}",
    # typography
    "body":            "{{FONT_BODY}}",
    "heading":         "{{FONT_HEADING}}",
}


def run(config: Config, tokens: DesignTokens, content: ContentInventory) -> None:
    rebrand_dir = ensure_dir(config.output_dir / "rebrand")

    # 1. Originals (verbatim copy)
    write_model(rebrand_dir / "tokens.original.json", tokens)
    write_model(rebrand_dir / "content.original.json", content)

    # 2. Templated tokens
    token_swap_map: dict[str, str] = {}
    templated_tokens = tokens.model_copy(deep=True)

    if templated_tokens.color.brand.primary:
        token_swap_map[templated_tokens.color.brand.primary.value] = PLACEHOLDER_TOKENS["brand.primary"]
        templated_tokens.color.brand.primary.value = PLACEHOLDER_TOKENS["brand.primary"]
    if templated_tokens.color.brand.secondary:
        token_swap_map[templated_tokens.color.brand.secondary.value] = PLACEHOLDER_TOKENS["brand.secondary"]
        templated_tokens.color.brand.secondary.value = PLACEHOLDER_TOKENS["brand.secondary"]

    for k, v in (("success", templated_tokens.color.accent.success),
                 ("warning", templated_tokens.color.accent.warning),
                 ("danger",  templated_tokens.color.accent.danger),
                 ("info",    templated_tokens.color.accent.info)):
        if v:
            placeholder = PLACEHOLDER_TOKENS[f"accent.{k}"]
            token_swap_map[v.value] = placeholder
            v.value = placeholder

    # Family swaps
    for name, family_def in templated_tokens.typography.families.items():
        ph = PLACEHOLDER_TOKENS.get(name)
        if ph:
            token_swap_map[family_def.primary] = ph
            family_def.primary = ph
            family_def.stack = ph + ", " + ", ".join(family_def.stack.split(",")[1:])

    write_model(rebrand_dir / "tokens.template.json", templated_tokens)

    # 3. Templated content
    copy_swap_map: dict[str, str] = {}
    templated_content = content.model_copy(deep=True)
    for slug, page in templated_content.pages.items():
        slug_upper = re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_")
        if page.title:
            ph = f"{{{{PAGE_{slug_upper}_TITLE}}}}"
            copy_swap_map[page.title] = ph
            page.title = ph
        if page.description:
            ph = f"{{{{PAGE_{slug_upper}_DESCRIPTION}}}}"
            copy_swap_map[page.description] = ph
            page.description = ph
        for i, section in enumerate(page.sections):
            if section.heading:
                ph = f"{{{{PAGE_{slug_upper}_SECTION_{i}_HEADING}}}}"
                copy_swap_map[section.heading] = ph
                section.heading = ph
            for j, para in enumerate(section.paragraphs):
                ph = f"{{{{PAGE_{slug_upper}_SECTION_{i}_PARA_{j}}}}}"
                copy_swap_map[para] = ph
                section.paragraphs[j] = ph
            for j, cta in enumerate(section.ctas):
                ph = f"{{{{PAGE_{slug_upper}_SECTION_{i}_CTA_{j}}}}}"
                copy_swap_map[cta.text] = ph
                cta.text = ph

    write_model(rebrand_dir / "content.template.json", templated_content)

    # 4. Swap map
    swap = SwapMap(
        tokens=token_swap_map,
        copy=copy_swap_map,
        meta=SwapMapMeta(
            token_count=len(token_swap_map),
            copy_count=len(copy_swap_map),
            generated_at=datetime.utcnow(),
        ),
    )
    write_model(rebrand_dir / "swap-map.json", swap)

    # 5. README
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    readme = env.get_template("rebrand_readme.md.j2").render(
        domain=config.domain,
        token_count=swap.meta.token_count,
        copy_count=swap.meta.copy_count,
    )
    (rebrand_dir / "README.md").write_text(readme, encoding="utf-8")
