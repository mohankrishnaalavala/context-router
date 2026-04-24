"""User endpoint handlers."""


def list_users() -> list[dict]:
    return []


def create_user(payload: dict) -> dict:
    return {"id": "u_1"}


def get_user(user_id: str) -> dict:
    return {"id": user_id}


def set_user_roles(user_id: str, roles: list[str]) -> dict:
    return {"id": user_id, "roles": roles}
