from decimal import Decimal, InvalidOperation

PRICE_UNITS = {"kg"}


def parse_pricing_rule(
    pricing_mode,
    price_unit,
    reference_price,
    price_range,
    minimum_price,
    maximum_price,
):
    if pricing_mode not in {"range", "bounds"}:
        raise ValueError("Price rule must be 'range' or 'bounds'.")
    if price_unit not in PRICE_UNITS:
        raise ValueError("The only supported price unit is kg.")

    def read_price(value, label, required=False):
        value = str(value).strip() if value is not None else ""
        if not value:
            if required:
                raise ValueError(f"{label} is required.")
            return None
        try:
            price = Decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"{label} must be a valid amount.") from error
        if not price.is_finite():
            raise ValueError(f"{label} must be a finite amount.")
        try:
            normalized_price = price.quantize(Decimal("0.01"))
        except InvalidOperation as error:
            raise ValueError(
                f"{label} must be no more than ₱99,999,999.99."
            ) from error
        if normalized_price != price or price > Decimal("99999999.99"):
            raise ValueError(
                f"{label} must be no more than ₱99,999,999.99 "
                "with two decimal places."
            )
        return price

    reference = read_price(reference_price, "Reference price", pricing_mode == "range")
    range_value = read_price(price_range, "Allowed range", pricing_mode == "range")
    minimum = read_price(minimum_price, "Minimum price", pricing_mode == "bounds")
    maximum = read_price(maximum_price, "Maximum price", pricing_mode == "bounds")

    if pricing_mode == "range":
        if reference <= 0 or range_value < 0:
            raise ValueError("Specific price must be positive and range cannot be negative.")
        if reference - range_value <= 0:
            raise ValueError("Allowed range must be less than the specific price.")
        minimum = maximum = None
    else:
        if minimum <= 0 or maximum < minimum:
            raise ValueError(
                "Minimum price must be positive and no greater than maximum price."
            )
        if reference is not None and not minimum <= reference <= maximum:
            raise ValueError(
                "Reference price must be within the minimum and maximum."
            )
        range_value = None

    return {
        "pricing_mode": pricing_mode,
        "price_unit": price_unit,
        "reference_price": float(reference) if reference is not None else None,
        "price_range": float(range_value) if range_value is not None else None,
        "minimum_price": float(minimum) if minimum is not None else None,
        "maximum_price": float(maximum) if maximum is not None else None,
    }


def price_bounds(pricing):
    if not pricing:
        return None

    mode = pricing["pricing_mode"]
    if mode == "range":
        reference = Decimal(str(pricing["reference_price"]))
        price_range = Decimal(str(pricing["price_range"]))
        minimum = reference - price_range
        maximum = reference + price_range
    elif mode == "bounds":
        reference = pricing["reference_price"]
        reference = Decimal(str(reference)) if reference is not None else None
        minimum = Decimal(str(pricing["minimum_price"]))
        maximum = Decimal(str(pricing["maximum_price"]))
    else:
        return None

    return {
        "reference": float(reference) if reference is not None else None,
        "minimum": float(minimum),
        "maximum": float(maximum),
        "unit": "kg",
    }


def price_is_allowed(price, bounds):
    if bounds is None:
        return True
    try:
        amount = Decimal(str(price))
        minimum = Decimal(str(bounds["minimum"]))
        maximum = Decimal(str(bounds["maximum"]))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return amount.is_finite() and minimum <= amount <= maximum


def seller_price_error(price, unit, pricing):
    bounds = price_bounds(pricing)
    if bounds is None:
        return None
    if unit != bounds["unit"]:
        return f"Admin pricing for this crop is set per {bounds['unit']}; choose that unit."
    if price_is_allowed(price, bounds):
        return None
    return (
        f"Admin pricing for this crop allows ₱{bounds['minimum']:.2f}–"
        f"₱{bounds['maximum']:.2f} per {bounds['unit']}."
    )
