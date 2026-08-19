"""Market intelligence and forecasting algorithms.

These functions are pure decision-support logic and deliberately do not depend
on Flask or database state.
"""

from collections import defaultdict
from datetime import datetime

def _parse_inventory_datetime(value):
    """Parse stored inventory timestamps in a tolerant way."""
    if not value:
        return datetime.now()

    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d")
        except ValueError:
            return datetime.now()


def _linear_forecast(values):
    """Return a simple linear forecast for the next period."""
    if not values:
        return 0
    if len(values) < 2:
        return max(0, int(values[-1]))

    x_values = list(range(len(values)))
    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(values) / len(values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)
    slope = numerator / denominator if denominator else 0
    intercept = mean_y - slope * mean_x
    forecast = intercept + slope * len(values)
    return max(0, int(round(forecast)))


def build_market_analysis(records):
    """Generate decision-support insights from inventory history."""
    if not records:
        return {
            "summary": {
                "total_quantity": 0,
                "active_crops": 0,
                "average_monthly_supply": 0,
                "market_pressure": "balanced",
                "current_month": datetime.now().strftime("%B")
            },
            "price_monitoring": [],
            "risk_alerts": [],
            "recommendations": [],
            "forecast": []
        }

    crop_totals = defaultdict(int)
    monthly_totals = defaultdict(int)
    crop_history = defaultdict(list)
    season_map = {
        "rice": [5, 6, 7, 8, 9, 10],
        "corn": [4, 5, 6, 7, 8],
        "banana": [1, 2, 3, 4, 5, 6],
        "mango": [3, 4, 5, 6, 7],
        "cabbage": [8, 9, 10, 11, 12],
        "eggplant": [4, 5, 6, 7, 8],
        "tomato": [1, 2, 3, 4, 5, 6],
        "cassava": [1, 2, 3, 4, 5, 6],
        "sugarcane": [7, 8, 9, 10, 11],
        "pepper": [5, 6, 7, 8, 9]
    }

    for row in records:
        crop_name = str(row["crop_name"] or "").strip()
        quantity = int(row["quantity"] or 0)
        if not crop_name or quantity <= 0:
            continue

        crop_totals[crop_name] += quantity
        month_key = _parse_inventory_datetime(row.get("date_received")).strftime("%Y-%m")
        monthly_totals[month_key] += quantity
        crop_history[crop_name].append((month_key, quantity))

    if not crop_totals:
        return {
            "summary": {
                "total_quantity": 0,
                "active_crops": 0,
                "average_monthly_supply": 0,
                "market_pressure": "balanced",
                "current_month": datetime.now().strftime("%B")
            },
            "price_monitoring": [],
            "risk_alerts": [],
            "recommendations": [],
            "forecast": []
        }

    month_values = list(monthly_totals.values())
    average_monthly_supply = round(sum(month_values) / len(month_values), 2) if month_values else 0
    current_month_name = datetime.now().strftime("%B")

    price_monitoring = []
    risk_alerts = []
    forecast = []

    for crop_name, total_quantity in sorted(crop_totals.items()):
        history_entries = sorted(crop_history.get(crop_name, []), key=lambda item: item[0])
        monthly_series = [value for _, value in history_entries]
        average_supply = sum(monthly_series) / len(monthly_series) if monthly_series else total_quantity
        supply_pressure = total_quantity / max(average_supply, 1)
        trend_change = 0
        if len(monthly_series) >= 2:
            trend_change = (monthly_series[-1] - monthly_series[-2]) / max(monthly_series[-2], 1)

        price_index = round(100 + (supply_pressure * 8) + (trend_change * 25) - 10)
        price_index = max(60, min(180, price_index))

        demand_score = min(1.0, supply_pressure / 1.5)
        seasonal_score = 1.0 if (datetime.now().month in season_map.get(crop_name.lower(), [])) else 0.7
        recommendation_score = round((demand_score * 0.45) + ((price_index - 80) / 100 * 0.35) + (seasonal_score * 0.2), 2)

        price_monitoring.append({
            "crop": crop_name,
            "current_supply": total_quantity,
            "average_supply": round(average_supply, 2),
            "price_index": price_index,
            "trend": "upward" if trend_change > 0 else "downward" if trend_change < 0 else "stable",
            "demand_signal": "strong" if demand_score >= 0.7 else "moderate" if demand_score >= 0.4 else "weak",
            "recommendation_score": recommendation_score
        })

        if supply_pressure >= 1.35:
            risk_alerts.append({
                "crop": crop_name,
                "type": "Oversupply risk",
                "message": f"Current supply for {crop_name} is {round(supply_pressure * 100)}% above the recent average.",
                "severity": "high"
            })
        elif supply_pressure <= 0.75:
            risk_alerts.append({
                "crop": crop_name,
                "type": "Undersupply risk",
                "message": f"Current supply for {crop_name} is {round((1 - supply_pressure) * 100)}% below the recent average.",
                "severity": "medium"
            })

        forecast.append({
            "crop": crop_name,
            "forecast_quantity": _linear_forecast(monthly_series),
            "trend": "increasing" if (monthly_series[-1] if monthly_series else 0) >= (monthly_series[-2] if len(monthly_series) > 1 else 0) else "decreasing",
            "recommendation_score": recommendation_score,
            "seasonal_fit": "favorable" if seasonal_score >= 0.9 else "neutral"
        })

    recommendations = sorted(
        [
            {
                "crop": item["crop"],
                "score": item["recommendation_score"],
                "reason": f"Demand signal is {item['demand_signal']} with a price index of {item['price_index']}"
            }
            for item in price_monitoring
        ],
        key=lambda item: item["score"],
        reverse=True
    )[:3]

    market_pressure = "balanced"
    if any(alert["type"] == "Oversupply risk" for alert in risk_alerts):
        market_pressure = "oversupply"
    if any(alert["type"] == "Undersupply risk" for alert in risk_alerts):
        market_pressure = "undersupply"

    return {
        "summary": {
            "total_quantity": sum(crop_totals.values()),
            "active_crops": len(crop_totals),
            "average_monthly_supply": average_monthly_supply,
            "market_pressure": market_pressure,
            "current_month": current_month_name
        },
        "price_monitoring": price_monitoring,
        "risk_alerts": risk_alerts,
        "recommendations": recommendations,
        "forecast": sorted(forecast, key=lambda item: item["forecast_quantity"], reverse=True)
    }
