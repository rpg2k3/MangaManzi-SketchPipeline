"""OS-native secure storage for API keys using keyring."""

import sys

import keyring

SERVICE_NAME = "9LivesK9"
ANTHROPIC_KEY = "anthropic_api_key"
PIXAI_KEY = "pixai_api_key"


def store_key(provider: str, api_key: str):
    keyring.set_password(SERVICE_NAME, provider, api_key)


def get_key(provider: str) -> str | None:
    """Return the stored key, or None if missing or unreadable.

    A keyring entry written by another tool can carry bytes that
    `keyring`'s SecretService backend can't UTF-8 decode (observed:
    UnicodeDecodeError on byte 0x93 — a smart-quote-shaped byte). In
    that case we treat the entry as missing so the app falls through
    to the onboarding flow instead of crashing at startup. The user
    can then re-enter the key, which overwrites the corrupt entry.
    """
    try:
        val = keyring.get_password(SERVICE_NAME, provider)
    except UnicodeDecodeError as e:
        print(
            f"[keyring] {provider}: stored value is not valid UTF-8 "
            f"({e}). Treating as missing — please re-enter the key in "
            "the Settings tab; that will overwrite the corrupt entry.",
            file=sys.stderr,
            flush=True,
        )
        return None
    except Exception as e:
        # Don't let any keyring backend exception crash launch.
        print(
            f"[keyring] {provider}: read failed ({type(e).__name__}: {e}). "
            "Treating as missing.",
            file=sys.stderr,
            flush=True,
        )
        return None
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
