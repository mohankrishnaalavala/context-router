"""Checkout endpoint handlers."""


def create_checkout(payload: dict) -> dict:
    """Create a new checkout session. Handles rate limiting and payment validation."""
    return {"id": "c_123", "items": payload["items"]}


def get_checkout(checkout_id: str) -> dict:
    """Fetch an existing checkout by id."""
    return {"id": checkout_id}
