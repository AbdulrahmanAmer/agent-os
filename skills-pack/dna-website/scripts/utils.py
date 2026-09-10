"""
Shared utilities. Most-used: URL handling, sanitization, hashing, path helpers.

CRITICAL: sanitize_network_log and sanitize_headers must be airtight. Any
sensitive data they miss ends up on disk. Add tests when you touch them.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import tldextract


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """
    Canonicalize a URL for deduplication:
    - lowercase scheme + host
    - drop default ports
    - drop fragment
    - sort query params
    - drop trailing slash on path except for root
    """
    p = urlparse(url)
    scheme = p.scheme.lower() or "https"
    netloc = p.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return urlunparse((scheme, netloc, path, p.params, query, ""))


def origin_of(url: str) -> str:
    """Return scheme://host[:port] for a URL."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def domain_of(url: str) -> str:
    """Return registrable domain, e.g. 'example.com' from 'https://app.example.com'."""
    ext = tldextract.extract(url)
    if not ext.domain:
        return urlparse(url).netloc
    if ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return ext.domain


def is_same_origin(a: str, b: str) -> bool:
    return origin_of(a) == origin_of(b)


def is_same_registrable_domain(a: str, b: str) -> bool:
    return domain_of(a) == domain_of(b)


def url_to_slug(url: str) -> str:
    """
    Convert a URL to a directory-safe slug.
    https://example.com/          -> home
    https://example.com/about     -> about
    https://example.com/blog/p1   -> blog__p1
    https://example.com/?q=foo    -> home__q-foo
    """
    p = urlparse(url)
    path = (p.path or "/").strip("/")
    parts = path.split("/") if path else []

    if p.query:
        # Stable representation of query
        q_repr = "_".join(
            f"{k}-{v}" for k, v in sorted(parse_qsl(p.query, keep_blank_values=True))
        )
        parts.append(q_repr)

    if not parts:
        return "home"

    slug = "__".join(parts)
    slug = _slugify(slug)
    return slug or "home"


def _slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9_\-]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def content_hash(data: bytes, length: int = 16) -> str:
    """Stable short hash of byte content. SHA-256 first N hex chars (default 16)."""
    return hashlib.sha256(data).hexdigest()[:length]


def file_hash(path: Path, length: int = 16) -> str:
    return content_hash(path.read_bytes(), length=length)


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

# Headers that must never be written to disk
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "proxy-authorization",
    "x-amz-security-token",
    "x-goog-api-key",
}

# JSON field names that should be redacted (case-insensitive, recursive)
SENSITIVE_JSON_FIELDS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "session",
    "session_id",
    "sessionid",
    "auth",
    "authorization",
    "credentials",
    "ssn",
}

# Query string keys to redact in URLs/logs
SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "refresh_token", "id_token",
    "api_key", "apikey", "key", "secret", "auth", "password",
    "code",  # OAuth authorization code — short-lived but still a token
}

# Substring patterns that indicate a token-shaped value
TOKEN_VALUE_PATTERNS = [
    re.compile(r"^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}$"),    # JWT
    re.compile(r"^sk_(live|test)_[A-Za-z0-9]{16,}$"),                                  # Stripe
    re.compile(r"^pk_(live|test)_[A-Za-z0-9]{16,}$"),
    re.compile(r"^rk_(live|test)_[A-Za-z0-9]{16,}$"),
    re.compile(r"^Bearer\s+[A-Za-z0-9._\-+/=]{20,}$"),
    re.compile(r"^ghp_[A-Za-z0-9]{20,}$"),                                              # GitHub PAT
    re.compile(r"^xox[abprs]-[A-Za-z0-9-]{10,}$"),                                      # Slack
]

REDACTED = "[REDACTED]"


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with sensitive ones redacted."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            out[k] = REDACTED
        elif _looks_like_token(v):
            out[k] = REDACTED
        else:
            out[k] = v
    return out


def sanitize_url(url: str) -> str:
    """Strip sensitive query parameters from a URL."""
    p = urlparse(url)
    if not p.query:
        return url
    pairs = parse_qsl(p.query, keep_blank_values=True)
    cleaned = [(k, REDACTED if k.lower() in SENSITIVE_QUERY_KEYS or _looks_like_token(v) else v)
               for k, v in pairs]
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(cleaned), p.fragment))


def sanitize_json(data: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive fields in a JSON-ish structure."""
    if _depth > 20:
        return REDACTED
    if isinstance(data, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_JSON_FIELDS
                else sanitize_json(v, _depth + 1))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [sanitize_json(item, _depth + 1) for item in data]
    if isinstance(data, str) and _looks_like_token(data):
        return REDACTED
    return data


def _looks_like_token(value: str) -> bool:
    if not isinstance(value, str) or len(value) < 16:
        return False
    return any(p.match(value) for p in TOKEN_VALUE_PATTERNS)


def extract_json_shape(data: Any, _depth: int = 0) -> Any:
    """
    Return the *shape* of a JSON document — keys preserved, scalar values
    replaced with their type. Used for capturing API response shapes
    without storing sensitive content.

        extract_json_shape({"user": {"id": 5, "name": "x"}})
        -> {"user": {"id": "int", "name": "str"}}
    """
    if _depth > 20:
        return "TRUNCATED"
    if isinstance(data, dict):
        return {k: extract_json_shape(v, _depth + 1) for k, v in data.items()}
    if isinstance(data, list):
        if not data:
            return ["empty"]
        # Show shape of first element + length
        return [extract_json_shape(data[0], _depth + 1), f"len={len(data)}"]
    return type(data).__name__


def sanitize_network_log(entries: list[dict]) -> list[dict]:
    """Apply all sanitization to a list of network entries before writing to disk."""
    out = []
    for e in entries:
        sanitized = dict(e)
        sanitized["url"] = sanitize_url(e.get("url", ""))
        sanitized["request_headers"] = sanitize_headers(e.get("request_headers") or {})
        sanitized["response_headers"] = sanitize_headers(e.get("response_headers") or {})
        if e.get("request_body_shape") is not None:
            sanitized["request_body_shape"] = sanitize_json(e["request_body_shape"])
        if e.get("response_body_shape") is not None:
            sanitized["response_body_shape"] = sanitize_json(e["response_body_shape"])
        out.append(sanitized)
    return out


# ---------------------------------------------------------------------------
# Purchase URL blocklist (hard rule — no purchases, no charges, no commitments)
# ---------------------------------------------------------------------------
#
# The crawler navigates pages but never clicks buy/checkout/pay buttons and
# never submits forms. So merely VIEWING a page like /pricing, /cart, /upgrade
# is safe — it just renders the UI. What's not safe is visiting URLs that
# perform an action on GET, e.g. /confirm-purchase or ?action=buy.
#
# This list therefore covers URLs where the GET itself is the action:
#   - /confirm-purchase, /confirm-order, /complete-purchase
#   - /charge, /charges/<id>/capture
#   - /plan/change (some sites complete a plan change on GET)
#   - Query-string action=buy|purchase|upgrade|subscribe|topup
#   - Tokens like /pay-now/<id> where visiting confirms a held payment
#
# Pages like /pricing, /checkout, /cart, /upgrade, /subscribe, /order-list,
# /order-skiptrace are EXPLICITLY allowed — they're page UIs we want to
# capture. The crawler never clicks the buttons on them.
#
# Adding entries is fine. Removing entries from this narrow list is not.

PURCHASE_URL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # GET-as-action paths (visiting these may commit a transaction)
        r"/confirm-purchase(?:[/?]|$)",
        r"/confirm-order(?:[/?]|$)",
        r"/complete-purchase(?:[/?]|$)",
        r"/complete-order(?:[/?]|$)",
        r"/submit-payment(?:[/?]|$)",
        r"/charges?/[\w-]+/capture(?:[/?]|$)",
        r"/charges?/capture(?:[/?]|$)",
        r"/pay-now(?:[/?]|$)",
        r"/place-order(?:[/?]|$)",
        r"/finalize-(?:order|purchase|payment)(?:[/?]|$)",
        # Query-string action= triggers
        r"[?&]action=buy(?:[&#]|$)",
        r"[?&]action=purchase(?:[&#]|$)",
        r"[?&]action=upgrade(?:[&#]|$)",
        r"[?&]action=subscribe(?:[&#]|$)",
        r"[?&]action=confirm(?:[&#]|$)",
        r"[?&]action=charge(?:[&#]|$)",
        r"[?&]action=pay(?:[&#]|$)",
        r"[?&]confirm=(?:1|true|yes)(?:[&#]|$)",
        # Stripe / Braintree confirmation tokens directly in the URL imply
        # the server is about to capture a PaymentIntent on hit
        r"/payment-intent/[\w-]+/confirm(?:[/?]|$)",
    )
)


def is_purchase_url(url: str) -> bool:
    """
    Return True if the URL looks like it commits a purchase, upgrade, or
    charge ON GET. The crawler is allowed to VIEW pages like /pricing,
    /cart, /upgrade, /checkout — they just render the UI. It is never
    allowed to visit URLs where the navigation itself triggers a charge
    (confirmation endpoints, payment-intent captures, action= triggers).
    """
    if not url or not isinstance(url, str):
        return False
    return any(p.search(url) for p in PURCHASE_URL_PATTERNS)


# Element-text patterns we must never click or submit. Used only by the auth
# module's safety asserts — the crawler does not click anything at all.
PURCHASE_ELEMENT_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bbuy\b",
        r"\bpurchase\b",
        r"\bcheckout\b",
        r"\bpay\s+now\b",
        r"\bcomplete\s+order\b",
        r"\bconfirm\s+purchase\b",
        r"\bupgrade\b",
        r"\bupgrade\s+plan\b",
        r"\badd\s+credits?\b",
        r"\btop[- ]?up\b",
        r"\bsubscribe\b",
        r"\bstart\s+trial\b",
        r"\bstart\s+subscription\b",
        r"\bplace\s+order\b",
        r"\bsubmit\s+payment\b",
    )
)


def is_purchase_element_text(text: str) -> bool:
    """True if any visible-text/aria-label hits a purchase keyword."""
    if not text:
        return False
    return any(p.search(text) for p in PURCHASE_ELEMENT_TEXT_PATTERNS)


# ---------------------------------------------------------------------------
# HTML rewriting for the inspector
# ---------------------------------------------------------------------------

def rewrite_html_asset_paths(html: str, url_to_local: dict[str, str], base_url: str) -> str:
    """
    Rewrite asset references in an HTML document to point at local paths.

    Handles:
    - <img src> + srcset
    - <link href>
    - <script src>
    - <source src>
    - <video src> + <audio src>
    - background:url(...) in inline style attributes
    - <link rel="stylesheet"> contents (recursively, separately)

    Args:
        html: rendered HTML
        url_to_local: { absolute_url: local_path_relative_to_inspector_root }
        base_url: the page's URL, used to resolve relative paths
    """
    from urllib.parse import urljoin

    def resolve(href: str) -> str:
        return urljoin(base_url, href)

    def replace(match: re.Match, attr: str) -> str:
        original = match.group(2)
        absolute = resolve(original)
        absolute_norm = normalize_url(absolute) if absolute.startswith("http") else absolute
        local = url_to_local.get(absolute) or url_to_local.get(absolute_norm)
        if local:
            return f'{attr}="{local}"'
        return match.group(0)

    # src/href attributes
    for attr in ("src", "href"):
        pattern = re.compile(rf'\b({attr})\s*=\s*"([^"]+)"', re.IGNORECASE)
        html = pattern.sub(lambda m: replace(m, attr), html)

    # srcset
    def srcset_replace(match: re.Match) -> str:
        parts = match.group(2).split(",")
        out_parts = []
        for part in parts:
            tokens = part.strip().split()
            if not tokens:
                continue
            url = tokens[0]
            descriptor = " ".join(tokens[1:])
            absolute = resolve(url)
            local = url_to_local.get(absolute) or url_to_local.get(normalize_url(absolute))
            out_parts.append(f"{local or url} {descriptor}".strip())
        return f'srcset="{", ".join(out_parts)}"'
    html = re.sub(r'\b(srcset)\s*=\s*"([^"]+)"', srcset_replace, html, flags=re.IGNORECASE)

    # url(...) in style attributes
    def url_replace(match: re.Match) -> str:
        url = match.group(1).strip("'\"")
        absolute = resolve(url)
        local = url_to_local.get(absolute) or url_to_local.get(normalize_url(absolute))
        return f'url("{local or url}")'
    html = re.sub(r'url\(([^)]+)\)', url_replace, html)

    return html


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_to_output(path: Path, output_dir: Path) -> str:
    return str(path.relative_to(output_dir))
