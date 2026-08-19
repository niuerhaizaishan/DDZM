DEFAULT_AI_TRIGGER_PREFIXES = ("@总监事",)
BOT_PLATFORM_LABEL = "「Bot」"


def normalize_ai_mention(
    content: str,
    trigger_prefixes: tuple[str, ...] = DEFAULT_AI_TRIGGER_PREFIXES,
) -> str:
    _, value = _strip_ai_mention(content, trigger_prefixes)
    return value


def ai_mention_content(
    content: str,
    trigger_prefixes: tuple[str, ...] = DEFAULT_AI_TRIGGER_PREFIXES,
) -> str | None:
    matched, value = _strip_ai_mention(content, trigger_prefixes)
    return value if matched and value else None


def _strip_ai_mention(
    content: str, trigger_prefixes: tuple[str, ...]
) -> tuple[bool, str]:
    value = content.strip()
    prefixes = tuple(
        sorted(
            {prefix.strip() for prefix in trigger_prefixes if prefix.strip()},
            key=len,
            reverse=True,
        )
    )
    prefix = next(
        (
            item
            for item in prefixes
            if value.startswith(item)
            and (
                len(value) == len(item)
                or value[len(item)].isspace()
                or value[len(item) :].startswith(BOT_PLATFORM_LABEL)
            )
        ),
        None,
    )
    if prefix is None:
        return False, value
    value = value[len(prefix) :]
    if value[: len(BOT_PLATFORM_LABEL)].casefold() == BOT_PLATFORM_LABEL.casefold():
        value = value[len(BOT_PLATFORM_LABEL) :]
    return True, value.strip()
