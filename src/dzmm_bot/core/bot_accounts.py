"""Platform identities owned by automated accounts."""

BOT_PLATFORM_IDS = frozenset(
    {
        "25b04f1a-5aba-4b85-9d4c-db9b5026842c",
        "acb22871-3895-4e7d-83e5-14b5ca421561",
    }
)


def is_bot_platform_id(platform_id: str) -> bool:
    return platform_id in BOT_PLATFORM_IDS
