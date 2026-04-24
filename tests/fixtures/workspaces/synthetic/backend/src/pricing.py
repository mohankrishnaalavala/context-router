"""Pricing endpoint handlers."""


def list_pricing() -> list[dict]:
    """Return the full pricing catalog."""
    return []


def get_pricing(sku: str) -> dict:
    """Return pricing for a single SKU."""
    return {"sku": sku, "price_cents": 0}
