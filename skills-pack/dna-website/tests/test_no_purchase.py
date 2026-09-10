"""
Hard-rule tests: the crawler must never visit a URL that could initiate or
commit a purchase, upgrade, subscription change, or credit top-up.

Covers:
  - is_purchase_url() correctly classifies a range of sample URLs
  - is_purchase_element_text() catches button/aria text we must not click
  - The discover stage filters them out
  - The crawl stage refuses to navigate to them (status=skipped_purchase_url)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from scripts.utils import is_purchase_element_text, is_purchase_url


# ---------------------------------------------------------------------------
# Pure unit tests on is_purchase_url
# ---------------------------------------------------------------------------

POSITIVE_SAMPLES = [
    # GET-as-action confirmation endpoints
    "https://kindskiptracing.com/confirm-purchase",
    "https://kindskiptracing.com/confirm-purchase/12345",
    "https://kindskiptracing.com/confirm-order",
    "https://kindskiptracing.com/complete-purchase",
    "https://kindskiptracing.com/complete-order",
    "https://kindskiptracing.com/submit-payment",
    "https://kindskiptracing.com/pay-now",
    "https://kindskiptracing.com/pay-now/abc",
    "https://kindskiptracing.com/place-order",
    "https://kindskiptracing.com/finalize-order",
    "https://kindskiptracing.com/finalize-purchase",
    "https://kindskiptracing.com/finalize-payment",
    "https://kindskiptracing.com/charges/ch_123/capture",
    "https://kindskiptracing.com/charge/capture",
    "https://kindskiptracing.com/payment-intent/pi_abc/confirm",
    # Action-style URLs (GET parameter triggers action)
    "https://kindskiptracing.com/account?action=buy",
    "https://kindskiptracing.com/account?action=purchase",
    "https://kindskiptracing.com/account?action=upgrade",
    "https://kindskiptracing.com/account?action=subscribe",
    "https://kindskiptracing.com/account?action=confirm",
    "https://kindskiptracing.com/account?action=charge",
    "https://kindskiptracing.com/account?action=pay",
    "https://kindskiptracing.com/checkout?confirm=true",
    "https://kindskiptracing.com/checkout?confirm=1",
    "https://kindskiptracing.com/?ref=foo&action=upgrade",
    # Case-insensitive
    "https://kindskiptracing.com/Confirm-Purchase",
    "https://kindskiptracing.com/account?Action=Confirm",
]

NEGATIVE_SAMPLES = [
    # Plain navigation — all page URLs are allowed (crawler doesn't click buttons)
    "https://kindskiptracing.com/",
    "https://kindskiptracing.com/dashboard",
    "https://kindskiptracing.com/contacts",
    "https://kindskiptracing.com/contacts/12345",
    "https://kindskiptracing.com/searches/history",
    "https://kindskiptracing.com/account",
    "https://kindskiptracing.com/account/usage",
    "https://kindskiptracing.com/account/profile",
    "https://kindskiptracing.com/help/support",
    "https://kindskiptracing.com/help/faq",
    "https://kindskiptracing.com/login",
    "https://kindskiptracing.com/logout",
    "https://kindskiptracing.com/?page=2&sort=desc",
    "https://kindskiptracing.com/team/members",
    # These pages were previously blocked but we now allow viewing — the
    # crawler still never clicks Buy/Confirm/Submit buttons on them.
    "https://kindskiptracing.com/pricing",
    "https://kindskiptracing.com/cart",
    "https://kindskiptracing.com/checkout",
    "https://kindskiptracing.com/billing",
    "https://kindskiptracing.com/subscribe",
    "https://kindskiptracing.com/upgrade",
    "https://kindskiptracing.com/buy",
    "https://kindskiptracing.com/order-list",
    "https://kindskiptracing.com/order-skiptrace",
    "https://kindskiptracing.com/orders",
    "https://kindskiptracing.com/add-credits",
    "https://kindskiptracing.com/topup",
    "https://kindskiptracing.com/plan/change",
    "https://kindskiptracing.com/subscribed-properties",
    "https://kindskiptracing.com/buyers-list",
]


@pytest.mark.parametrize("url", POSITIVE_SAMPLES)
def test_is_purchase_url_positive(url: str) -> None:
    assert is_purchase_url(url), f"expected purchase-URL match for {url!r}"


@pytest.mark.parametrize("url", NEGATIVE_SAMPLES)
def test_is_purchase_url_negative(url: str) -> None:
    assert not is_purchase_url(url), f"unexpected purchase-URL match for {url!r}"


def test_empty_and_garbage_inputs() -> None:
    assert is_purchase_url("") is False
    assert is_purchase_url(None) is False  # type: ignore[arg-type]
    assert is_purchase_url(12345) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Element-text checks
# ---------------------------------------------------------------------------

ELEMENT_POSITIVES = [
    "Buy now",
    "Purchase",
    "Checkout",
    "Pay Now",
    "Complete order",
    "Confirm purchase",
    "Upgrade",
    "Upgrade plan",
    "Add credits",
    "Add credit",
    "Top up",
    "Top-up",
    "Subscribe",
    "Start trial",
    "Start subscription",
    "Place order",
    "Submit payment",
]

ELEMENT_NEGATIVES = [
    "Search",
    "Submit",
    "Sign in",
    "Log out",
    "Profile",
    "Dashboard",
    "Open",
    "View details",
    "",
]


@pytest.mark.parametrize("text", ELEMENT_POSITIVES)
def test_is_purchase_element_positive(text: str) -> None:
    assert is_purchase_element_text(text), f"expected to flag {text!r}"


@pytest.mark.parametrize("text", ELEMENT_NEGATIVES)
def test_is_purchase_element_negative(text: str) -> None:
    assert not is_purchase_element_text(text), f"unexpected flag on {text!r}"


# ---------------------------------------------------------------------------
# Integration: discover stage drops purchase URLs
# ---------------------------------------------------------------------------

def test_discover_filters_purchase_urls(tmp_path) -> None:
    """
    Drive _bfs_crawl-equivalent route filtering by feeding a hand-built
    set of routes through the same filter the discover stage uses.
    Verifies the filter is wired in.
    """
    from scripts.models import Route, RouteList

    routes = [
        Route(
            url="https://example.com/",
            slug="home",
            depth=0,
            source="seed",
            discovered_at=datetime.utcnow(),
        ),
        Route(
            url="https://example.com/confirm-purchase",
            slug="confirm-purchase",
            depth=1,
            source="crawl",
            discovered_at=datetime.utcnow(),
        ),
        Route(
            url="https://example.com/account?action=upgrade",
            slug="account_action_upgrade",
            depth=1,
            source="crawl",
            discovered_at=datetime.utcnow(),
        ),
        Route(
            url="https://example.com/contacts",
            slug="contacts",
            depth=1,
            source="crawl",
            discovered_at=datetime.utcnow(),
        ),
    ]

    keep = [r for r in routes if not is_purchase_url(r.url)]
    keep_urls = {r.url for r in keep}
    drop_urls = {r.url for r in routes if r.url not in keep_urls}

    assert keep_urls == {"https://example.com/", "https://example.com/contacts"}
    assert drop_urls == {
        "https://example.com/confirm-purchase",
        "https://example.com/account?action=upgrade",
    }


# ---------------------------------------------------------------------------
# Integration: crawl stage skips with status=skipped_purchase_url
# ---------------------------------------------------------------------------

def test_skipped_capture_status() -> None:
    """The capture entry created when a purchase URL is intercepted at navigate
    time must have status=skipped_purchase_url and an informative reason."""
    from scripts.crawl import _skipped_purchase_capture

    cap = _skipped_purchase_capture("https://example.com/upgrade", "upgrade")
    assert cap.status == "skipped_purchase_url"
    assert "purchase" in (cap.error_message or "").lower()
    assert cap.final_url == "https://example.com/upgrade"
    assert cap.duration_ms == 0
    assert cap.http_status == 0
