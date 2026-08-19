BOT_GROUP_MAX_CHARS = 1000
BOT_GROUP_MAX_NEWLINES = 10


def group_message_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    current: str | None = None
    for line_number, line in enumerate(text.split("\n")):
        remaining = line
        first_piece = True
        while remaining or first_piece:
            first_piece = False
            capacity = BOT_GROUP_MAX_CHARS
            if current is not None:
                capacity -= len(current) + (1 if line_number else 0)
            if capacity <= 0 or (
                current is not None
                and line_number
                and current.count("\n") >= BOT_GROUP_MAX_NEWLINES
            ):
                chunks.append(current)
                current = None
                continue
            piece = remaining[:capacity]
            remaining = remaining[capacity:]
            if current is None:
                current = piece
            elif line_number:
                current = f"{current}\n{piece}"
            else:
                current += piece
            if remaining:
                chunks.append(current)
                current = None
    if current is not None:
        chunks.append(current)
    return chunks


def requires_bot_group_sender(text: str) -> bool:
    return (
        len(text) > BOT_GROUP_MAX_CHARS
        or text.count("\n") > BOT_GROUP_MAX_NEWLINES
    )
