"""
Pydantic models for every JSON file the tool reads or writes.

This module is the single source of truth for data shapes. Whenever you change
a schema, bump SCHEMA_VERSION at the bottom and add migration logic in
load_manifest if needed.

All readers/writers MUST go through these models. Never raw-dump or raw-load.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

class PreflightFlags(BaseModel):
    ignore_robots: bool = False
    i_own_this_site: bool = False
    include_subdomains: bool = False


class PreflightResult(BaseModel):
    url: str
    normalized_url: str
    domain: str
    base_origin: str                  # scheme://host[:port]
    blocked_category: str | None = None
    robots_allowed: bool = True
    robots_disallow_paths: list[str] = Field(default_factory=list)
    user_confirmed_override: bool = False
    flags: PreflightFlags
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

RouteSource = Literal["sitemap", "robots-disallow", "crawl", "spa-sniff", "manual", "seed"]


class Route(BaseModel):
    url: str
    slug: str
    depth: int = 0
    source: RouteSource = "crawl"
    auth_required: bool = False
    discovered_at: datetime


class RouteList(BaseModel):
    base_origin: str
    routes: list[Route]


# ---------------------------------------------------------------------------
# Crawl outputs
# ---------------------------------------------------------------------------

class Viewport(BaseModel):
    width: int
    height: int


class CaptureFiles(BaseModel):
    source_html: str
    rendered_html: str
    screenshot_desktop: str
    screenshot_mobile: str | None = None
    computed_styles: str
    dom_tree: str
    a11y_tree: str
    network_log: str
    meta: str


class Capture(BaseModel):
    url: str
    slug: str
    status: Literal["ok", "error", "skipped_purchase_url"] = "ok"
    error_message: str | None = None
    duration_ms: int
    http_status: int
    redirected_to: str | None = None
    final_url: str | None = None
    files: CaptureFiles
    viewport: Viewport


class CaptureManifest(BaseModel):
    total: int
    successful: int
    failed: int
    captures: list[Capture]


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ElementStyles(BaseModel):
    tag: str
    classes: list[str] = Field(default_factory=list)
    id: str | None = None
    role: str | None = None
    path: str
    text: str | None = None
    styles: dict[str, str]
    bbox: BBox | None = None


class ComputedStylesDoc(BaseModel):
    page_slug: str
    captured_at: datetime
    elements: list[ElementStyles]


class NetworkEntry(BaseModel):
    url: str
    method: str
    resource_type: str
    status: int
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body_shape: dict[str, Any] | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body_shape: dict[str, Any] | None = None
    response_size: int = 0
    duration_ms: int = 0
    initiator: str | None = None


class NetworkLog(BaseModel):
    page_slug: str
    entries: list[NetworkEntry]


class PageMeta(BaseModel):
    url: str
    final_url: str
    title: str = ""
    description: str | None = None
    canonical: str | None = None
    og: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    json_ld: list[dict[str, Any]] = Field(default_factory=list)
    lang: str | None = None
    viewport: str | None = None
    favicon: str | None = None
    manifest_url: str | None = None


class DomNode(BaseModel):
    tag: str
    id: str | None = None
    classes: list[str] = Field(default_factory=list)
    role: str | None = None
    children: list["DomNode"] = Field(default_factory=list)


class DomTree(BaseModel):
    root: DomNode


class A11yNode(BaseModel):
    role: str
    name: str | None = None
    value: str | None = None
    description: str | None = None
    children: list["A11yNode"] = Field(default_factory=list)


class A11yTree(BaseModel):
    root: A11yNode | None


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

AssetType = Literal["image", "font", "icon", "video", "stylesheet", "script"]
DownloadStatus = Literal["ok", "failed", "skipped"]


class Asset(BaseModel):
    original_url: str
    local_path: str
    content_hash: str
    content_type: str
    size_bytes: int
    type: AssetType
    used_on_pages: list[str] = Field(default_factory=list)
    download_status: DownloadStatus = "ok"
    failure_reason: str | None = None


class AssetStats(BaseModel):
    total: int
    by_type: dict[str, int] = Field(default_factory=dict)
    total_bytes: int = 0
    failed: int = 0
    skipped_oversized: int = 0


class AssetManifest(BaseModel):
    assets: list[Asset]
    by_url: dict[str, str] = Field(default_factory=dict)
    stats: AssetStats


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

class TokenValue(BaseModel):
    value: str
    frequency: int | None = None


class BrandColors(BaseModel):
    primary: TokenValue | None = None
    secondary: TokenValue | None = None


class AccentColors(BaseModel):
    success: TokenValue | None = None
    warning: TokenValue | None = None
    danger: TokenValue | None = None
    info: TokenValue | None = None


class ColorCluster(BaseModel):
    centroid: str
    size: int
    members: list[str]
    saturation: float
    lightness: float
    classification: str


class ColorPalette(BaseModel):
    brand: BrandColors = Field(default_factory=BrandColors)
    neutrals: dict[str, TokenValue] = Field(default_factory=dict)
    accent: AccentColors = Field(default_factory=AccentColors)
    tertiary: list[TokenValue] = Field(default_factory=list)
    raw_clusters: list[ColorCluster] = Field(default_factory=list)


class FontFamilyDef(BaseModel):
    stack: str
    primary: str


class FontSize(BaseModel):
    px: float
    rem: float


class TypographyScale(BaseModel):
    ratio: float | None
    base_px: float
    sizes: dict[str, FontSize]


class TypographySystem(BaseModel):
    families: dict[str, FontFamilyDef]
    scale: TypographyScale
    weights: list[int]
    line_heights: dict[str, float]
    letter_spacing: dict[str, str]


class SpacingEntry(BaseModel):
    px: float
    rem: float


class SpacingSystem(BaseModel):
    base_unit_px: int
    scale: dict[str, SpacingEntry]
    raw_values: list[float]


class RadiusSystem(BaseModel):
    scale: dict[str, int]   # name -> px (9999 = "full")


class ShadowSystem(BaseModel):
    scale: dict[str, str]
    inner: dict[str, str] = Field(default_factory=dict)


class MotionSystem(BaseModel):
    duration: dict[str, str]
    easing: dict[str, str]
    keyframes: dict[str, dict[str, str]] = Field(default_factory=dict)


class BreakpointSystem(BaseModel):
    scale: dict[str, str]
    raw: list[int]


class DesignTokens(BaseModel):
    schema_field: str = Field(default="design-tokens.v1", alias="$schema")
    generated_at: datetime
    color: ColorPalette
    typography: TypographySystem
    spacing: SpacingSystem
    radius: RadiusSystem
    shadow: ShadowSystem
    motion: MotionSystem
    breakpoint: BreakpointSystem

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Components and icons
# ---------------------------------------------------------------------------

class ComponentExample(BaseModel):
    page: str
    path: str
    html_snippet: str


class ComponentPattern(BaseModel):
    id: str
    role_guess: str
    occurrence_count: int
    signature: list[Any]   # nested tuple-as-list
    common_classes: list[str]
    examples: list[ComponentExample]


class ComponentPatterns(BaseModel):
    patterns: list[ComponentPattern]


class InlineSvg(BaseModel):
    hash: str
    path: str
    used_on: list[str]
    guessed_name: str
    viewBox: str | None = None


class IconFont(BaseModel):
    family: str
    classes_used: list[str]


class IconLibrary(BaseModel):
    inline_svgs: list[InlineSvg] = Field(default_factory=list)
    icon_fonts: list[IconFont] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

class ContentLink(BaseModel):
    text: str
    href: str


class ContentImage(BaseModel):
    src: str
    alt: str = ""
    caption: str | None = None


class ContentCTA(BaseModel):
    text: str
    href: str | None = None
    kind: Literal["button", "link"] = "link"


class ContentSection(BaseModel):
    id: str | None = None
    heading: str | None = None
    level: int | None = None
    paragraphs: list[str] = Field(default_factory=list)
    links: list[ContentLink] = Field(default_factory=list)
    images: list[ContentImage] = Field(default_factory=list)
    ctas: list[ContentCTA] = Field(default_factory=list)


class PageContent(BaseModel):
    url: str
    title: str
    description: str | None = None
    sections: list[ContentSection] = Field(default_factory=list)


class ContentInventory(BaseModel):
    pages: dict[str, PageContent]


class IANode(BaseModel):
    slug: str
    url: str
    title: str
    depth: int
    children: list["IANode"] = Field(default_factory=list)


class IATree(BaseModel):
    root: IANode


# ---------------------------------------------------------------------------
# Rebrand
# ---------------------------------------------------------------------------

class SwapMapMeta(BaseModel):
    token_count: int
    copy_count: int
    generated_at: datetime


class SwapMap(BaseModel):
    tokens: dict[str, str]
    copy: dict[str, str]
    meta: SwapMapMeta

    model_config = {"protected_namespaces": (), "ignored_types": ()}


# ---------------------------------------------------------------------------
# Auth profile
# ---------------------------------------------------------------------------

class AuthProfile(BaseModel):
    """Auth profile loaded from .dna-website.env.

    Supports two key schemas:
      - Lowercase / strategy-based (preferred): url, strategy, login_url, email,
        password, post_login_url_pattern, verify_session_url, verify_session_success
      - Legacy UPPERCASE: LOGIN_URL, USERNAME, PASSWORD, POST_LOGIN_URL_CONTAINS,
        MANUAL_LOGIN, etc.
    """

    name: str
    login_url: str
    username: str                                 # mirrors `email` from lowercase schema
    password: str = Field(..., repr=False)        # never display

    # Optional target URL (lowercase schema's `url`)
    url: str | None = None

    # Strategy: "manual" | "automated" | "cookie_paste"
    strategy: str = "manual"

    # Selectors (used when strategy == "automated")
    username_selector: str = 'input[type="email"], input[name="email"]'
    password_selector: str = 'input[type="password"], input[name="password"]'
    submit_selector: str = 'button[type="submit"]'

    # Post-login waiting conditions — keep both styles for compatibility
    post_login_url_contains: str = "/"
    post_login_url_pattern: str | None = None     # regex; takes precedence if set
    post_login_selector: str | None = None

    # Session verification
    verify_session_url: str | None = None
    verify_session_success: str | None = None     # regex matched against page content

    # 2FA mode
    two_factor: str = "manual"   # "none" | "manual" | "totp:<secret>"

    # Legacy bools (kept for backward compatibility — strategy is preferred)
    manual_login: bool = False
    manual_cookie_paste: bool = False

    # Misc
    cookie_domain: str | None = None
    test_url: str | None = None

    def safe_repr(self) -> str:
        return f"AuthProfile(name={self.name!r}, login_url={self.login_url!r}, username={self.username!r}, password=***)"

    @property
    def email(self) -> str:
        """Alias for username — matches the lowercase INI schema."""
        return self.username

    @property
    def effective_strategy(self) -> str:
        """Resolve strategy from the new key and the legacy bools."""
        if self.manual_cookie_paste:
            return "cookie_paste"
        if self.manual_login:
            return "manual"
        return (self.strategy or "manual").lower()


# ---------------------------------------------------------------------------
# Run manifest (top-level, written last)
# ---------------------------------------------------------------------------

class RunStats(BaseModel):
    pages_crawled: int = 0
    pages_failed: int = 0
    assets_downloaded: int = 0
    assets_failed: int = 0
    total_bytes: int = 0
    unique_colors: int = 0
    unique_fonts: int = 0
    component_patterns_detected: int = 0


class RunFiles(BaseModel):
    report: str = "REPORT.md"
    routes: str = "routes.json"
    captures: str = "captures.json"
    assets: str = "asset_manifest.json"
    design_tokens: str = "analysis/design-tokens.json"
    content: str = "analysis/content-inventory.json"
    ia: str = "analysis/information-architecture.json"
    inspector_index: str = "inspector/index.html"


SCHEMA_VERSION = "1.0"


class RunManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    target_url: str
    base_origin: str
    domain: str
    output_dir: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    flags: dict[str, Any] = Field(default_factory=dict)
    stats: RunStats = Field(default_factory=RunStats)
    files: RunFiles = Field(default_factory=RunFiles)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def write_model(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model to a JSON file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2, by_alias=True))


def load_model(path: Path, model_cls: type[BaseModel]) -> BaseModel:
    """Load and validate a JSON file against a Pydantic model."""
    return model_cls.model_validate_json(path.read_text())


def load_manifest(path: Path) -> RunManifest:
    """Load a top-level manifest. Adds migration logic when SCHEMA_VERSION changes."""
    data = path.read_text()
    manifest = RunManifest.model_validate_json(data)
    # Future: check manifest.schema_version and migrate.
    return manifest
