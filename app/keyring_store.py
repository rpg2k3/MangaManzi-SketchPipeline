"""OS-native secure storage for API keys using keyring."""

import keyring

SERVICE_NAME = "9LivesK9"
ANTHROPIC_KEY = "anthropic_api_key"
PIXAI_KEY = "pixai_api_key"


def store_key(provider: str, api_key: str):
    keyring.set_password(SERVICE_NAME, provider, api_key)


def get_key(provider: str) -> str | None:
    val = keyring.get_password(SERVICE_NAME, provider)
    return val if val else None


def delete_key(provider: str):
    try:
        keyring.delete_password(SERVICE_NAME, provider)
    except keyring.errors.PasswordDeleteError:
        pass


def get_anthropic_key() -> str | None:
    return get_key(ANTHROPIC_KEY)


def set_anthropic_key(key: str):
    store_key(ANTHROPIC_KEY, key)


def get_pixai_key() -> str | None:
    return get_key(PIXAI_KEY)


def set_pixai_key(key: str):
    store_key(PIXAI_KEY, key)


def mask_key(key: str | None) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def clear_all():
    delete_key(ANTHROPIC_KEY)
    delete_key(PIXAI_KEY)
