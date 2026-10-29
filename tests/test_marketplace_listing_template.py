import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def test_add_listing_renders_inventory_crop_as_option_text():
    crop = {
        "id": 1,
        "crops_name": "Tomatoes",
        "total_quantity": 12,
        "pricing_mode": None,
        "reference_price": None,
        "price_range": None,
        "minimum_price": None,
        "maximum_price": None,
    }

    with app_module.app.test_request_context("/marketplace/add"):
        rendered = app_module.app.jinja_env.get_template("add_listing.html").render(
            listing=None,
            crops=[crop],
            all_crops=[],
            cart_count=0,
            profile_location_verified=False,
            user_inventory=[],
        )

    assert '<option value="1"' in rendered
    assert ">Tomatoes (12 available)" in rendered
