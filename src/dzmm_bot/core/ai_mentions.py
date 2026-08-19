BOT_MENTION_PREFIX = "@总监事"
BOT_PLATFORM_LABEL = "「Bot」"


def normalize_ai_mention(
    content: str, mention_names: tuple[str, ...] = ()
) -> str:
    _, value = _strip_ai_mention(content, mention_names)
    return value


def ai_mention_content(
    content: str, mention_names: tuple[str, ...] = ()
) -> str | None:
    matched, value = _strip_ai_mention(content, mention_names)
    return value if matched and value else None


def _strip_ai_mention(
    content: str, mention_names: tuple[str, ...]
) -> tuple[bool, str]:
    value = content.strip()
    prefixes = tuple(
        sorted(
            {BOT_MENTION_PREFIX, *(f"@{name.strip()}" for name in mention_names if name.strip())},
            key=len,
            reverse=True,
        )
    )
    prefix = next((item for item in prefixes if value.startswith(item)), None)
    if prefix is None:
        return False, value
    value = value[len(prefix) :]
    if value[: len(BOT_PLATFORM_LABEL)].casefold() == BOT_PLATFORM_LABEL.casefold():
        value = value[len(BOT_PLATFORM_LABEL) :]
    return True, value.strip()
