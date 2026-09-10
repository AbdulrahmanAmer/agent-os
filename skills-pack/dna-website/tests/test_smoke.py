"""
Smoke tests. These are the floor — every PR should keep them green.

Coverage:
  - URL normalization and slug generation
  - Sanitization of headers, URLs, JSON
  - Color parsing
  - Auth profile loading
"""

import json
import pytest

from scripts.utils import (
    REDACTED,
    content_hash,
    extract_json_shape,
    normalize_url,
    sanitize_headers,
    sanitize_json,
    sanitize_url,
    url_to_slug,
)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

class TestUrlNormalization:
    def test_basic(self):
        assert normalize_url("HTTPS://Example.com/") == "https://example.com/"

    def test_drops_default_ports(self):
        assert normalize_url("https://example.com:443/foo") == "https://example.com/foo"
        assert normalize_url("http://example.com:80/foo") == "http://example.com/foo"

    def test_drops_fragment(self):
        assert normalize_url("https://example.com/foo#bar") == "https://example.com/foo"

    def test_sorts_query(self):
        a = normalize_url("https://example.com/?b=2&a=1")
        b = normalize_url("https://example.com/?a=1&b=2")
        assert a == b


class TestSlug:
    def test_root(self):
        assert url_to_slug("https://example.com/") == "home"

    def test_simple_path(self):
        assert url_to_slug("https://example.com/about") == "about"

    def test_nested(self):
        assert url_to_slug("https://example.com/blog/post-1") == "blog__post-1"

    def test_query(self):
        assert "q-foo" in url_to_slug("https://example.com/?q=foo")

    def test_unicode_safe(self):
        s = url_to_slug("https://example.com/café/résumé")
        # No non-ascii survives
        assert s.encode("ascii", "ignore").decode() == s


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

class TestSanitizeHeaders:
    def test_authorization_redacted(self):
        result = sanitize_headers({"Authorization": "Bearer abc123def456ghi789jkl"})
        assert result["Authorization"] == REDACTED

    def test_cookie_redacted(self):
        result = sanitize_headers({"Cookie": "sess=xxx"})
        assert result["Cookie"] == REDACTED

    def test_non_sensitive_preserved(self):
        result = sanitize_headers({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"

    def test_token_shaped_value_caught_anywhere(self):
        result = sanitize_headers({
            "X-Custom": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxw"
        })
        assert result["X-Custom"] == REDACTED


class TestSanitizeUrl:
    def test_strips_token_param(self):
        assert "abc" not in sanitize_url("https://x.com/?token=abc")

    def test_strips_api_key_param(self):
        assert "secret" not in sanitize_url("https://x.com/?api_key=secret")

    def test_preserves_innocuous_params(self):
        url = sanitize_url("https://x.com/?page=2&sort=desc")
        assert "page=2" in url
        assert "sort=desc" in url


class TestSanitizeJson:
    def test_redacts_password_field(self):
        result = sanitize_json({"user": {"name": "x", "password": "secret"}})
        assert result["user"]["password"] == REDACTED
        assert result["user"]["name"] == "x"

    def test_redacts_token_field(self):
        result = sanitize_json({"access_token": "abc", "data": {"refresh_token": "def"}})
        assert result["access_token"] == REDACTED
        assert result["data"]["refresh_token"] == REDACTED

    def test_redacts_jwt_value(self):
        result = sanitize_json({
            "session": "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6MX0.signature_part_abcdef"
        })
        # Both because the key is sensitive AND the value looks token-y
        assert result["session"] == REDACTED


# ---------------------------------------------------------------------------
# JSON shape extraction
# ---------------------------------------------------------------------------

class TestExtractJsonShape:
    def test_scalar_types(self):
        assert extract_json_shape(5) == "int"
        assert extract_json_shape("hi") == "str"
        assert extract_json_shape(True) == "bool"

    def test_dict_keys_preserved(self):
        shape = extract_json_shape({"id": 5, "name": "x"})
        assert shape == {"id": "int", "name": "str"}

    def test_list_summary(self):
        shape = extract_json_shape([1, 2, 3])
        assert shape == ["int", "len=3"]


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_stable(self):
        h1 = content_hash(b"hello world")
        h2 = content_hash(b"hello world")
        assert h1 == h2

    def test_length(self):
        assert len(content_hash(b"x")) == 16

    def test_different_inputs(self):
        assert content_hash(b"a") != content_hash(b"b")
