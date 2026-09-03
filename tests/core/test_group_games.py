from dzmm_bot.core.group_games import (
    GROUP_GAME_COMMANDS,
    GROUP_GAME_LABELS,
    GROUP_GAME_TYPES,
)


def test_never_have_i_ever_group_game_contract() -> None:
    assert "never_have_i_ever" in GROUP_GAME_TYPES
    assert GROUP_GAME_LABELS["never_have_i_ever"] == "我有你没有"
    assert GROUP_GAME_COMMANDS["/我有你没有"] == "never_have_i_ever"
    assert GROUP_GAME_COMMANDS["/发言"] == "never_have_i_ever"
    assert GROUP_GAME_COMMANDS["/扣"] == "never_have_i_ever"
    assert GROUP_GAME_COMMANDS["/不扣"] == "never_have_i_ever"


def test_king_game_group_game_contract() -> None:
    assert "king_game" in GROUP_GAME_TYPES
    assert GROUP_GAME_LABELS["king_game"] == "国王游戏"
    assert GROUP_GAME_COMMANDS["/国王游戏"] == "king_game"
    assert GROUP_GAME_COMMANDS["/公开"] == "king_game"
