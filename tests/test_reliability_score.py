from app.algorithms.reliability_score import seller_reliability_status


def test_seller_reliability_status_uses_five_star_rating_scale():
    assert seller_reliability_status(None) == "Not Yet Rated"
    assert seller_reliability_status(4.0) == "High Reliability"
    assert seller_reliability_status(3.0) == "Medium Reliability"
    assert seller_reliability_status(2.99) == "Low Reliability"
