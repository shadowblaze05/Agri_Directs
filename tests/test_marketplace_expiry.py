import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_marketplace_listing_displays_expiry_and_live_countdown():
    listing = {
        "id": 17,
        "commodity_name": "Tomato",
        "amount": 12,
        "price": 25,
        "unit": "kg",
        "listing_date": "2026-11-16 13:00:00",
        "expiry_date": "2026-11-18 15:30:00",
        "main_image": None,
        "commodity_default_image": None,
        "thumbnail_verified": False,
        "listing_type": "standard",
        "available_date": None,
        "seller_name": "seller",
        "reliability_score": None,
        "reliability_status": "Not Yet Rated",
        "seller_rating_count": 0,
    }

    with app_module.app.test_request_context("/marketplace"):
        rendered = app_module.app.jinja_env.get_template("marketplace.html").render(
            listings=[listing],
            user_inventory=[],
            commodities=[],
            pending_ratings=[],
            cart_count=0,
            marketplace_images_count={},
            default_listing_type="standard",
        )

    assert 'datetime="2026-11-18T15:30:00"' in rendered
    assert "2026-11-18 15:30" in rendered
    assert 'data-expiry="2026-11-18T15:30:00"' in rendered
    assert "Expires" in rendered
    assert "countdown.closest('.listing-item')" in rendered
    assert "listingItem.remove()" in rendered
    assert "No active listings available." in rendered
    assert "window.setInterval(updateListingExpiryCountdowns, 1000)" in rendered
