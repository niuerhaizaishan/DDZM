import pytest

from dzmm_bot.core.memory_guild_match import (
    parse_guild_match_start,
    parse_series_command,
    parse_team_command,
    render_guild_match_created,
    render_guild_match_finished,
    render_guild_round_result,
    render_guild_series_ready,
    split_roster_names,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/记忆考核 公会赛 1", 1),
        ("/记忆考核 公会赛 20", 20),
        (" /记忆考核   公会赛   3 ", 3),
        ("/记忆考核 公会赛 0", None),
        ("/记忆考核 公会赛 21", None),
        ("/记忆考核 公会赛 三", None),
        ("/记忆考核 对战", None),
    ],
)
def test_parse_guild_match_start_enforces_planned_series_range(content, expected):
    assert parse_guild_match_start(content) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/第1场 2/3", (1, 2, 3)),
        ("/第2场 3/5", (2, 3, 5)),
        (" /第12场   4/7 ", (12, 4, 7)),
        ("/第0场 2/3", None),
        ("/第1场 3/7", None),
        ("/第1场 2/4", None),
        ("/第1场 51/101", None),
    ],
)
def test_parse_series_command_only_accepts_strict_majority_formats(content, expected):
    assert parse_series_command(content) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/队伍1 女仆公馆队", (1, "name", "女仆公馆队")),
        ("/队伍2人员 G，彻", (2, "members", "G，彻")),
        ("/队伍3 不存在", None),
        ("/队伍1", None),
        ("/队伍1人员", None),
    ],
)
def test_parse_team_command_identifies_slot_and_field(content, expected):
    assert parse_team_command(content) == expected


def test_split_roster_names_accepts_common_separators_and_preserves_order():
    assert split_roster_names("G，彻, 苏白、饭饭") == ("G", "彻", "苏白", "饭饭")


def test_split_roster_names_rejects_empty_and_duplicate_names():
    with pytest.raises(ValueError, match="不能为空"):
        split_roster_names("， , 、")
    with pytest.raises(ValueError, match="重复"):
        split_roster_names("G，彻，G")


def test_render_created_match_uses_approved_visual_style():
    text = render_guild_match_created("苏白", 3)

    assert text.startswith("━━━━━━━━━━━━━━\n🏆 记忆考核 · 公会赛")
    assert "🎙️ 主持人：苏白" in text
    assert "📋 预设场次：3场" in text
    assert text.endswith("━━━━━━━━━━━━━━")


def test_render_ready_series_shows_pairing_and_host_action():
    text = render_guild_series_ready(
        sequence=1,
        win_target=4,
        maximum_decisive_rounds=7,
        team1_player="G",
        team2_player="彻",
        team1_wins=0,
        team2_wins=0,
        next_round_sequence=1,
    )

    assert "⚔️ 第1场 · 七局四胜" in text
    assert "🔴 G\n        VS\n🔵 彻" in text
    assert "📊 本场比分：0 : 0" in text
    assert "🎙️ 请主持人发送 /开始对战" in text


@pytest.mark.parametrize(
    ("winner_name", "expected"),
    [("G", "✅ G 赢得本局"), (None, "🤝 本局平局")],
)
def test_render_round_result_distinguishes_winner_and_draw(winner_name, expected):
    text = render_guild_round_result(
        series_sequence=1,
        round_sequence=2,
        winner_name=winner_name,
        team1_wins=1,
        team2_wins=0,
    )
    assert expected in text
    assert "📊 本场比分：1 : 0" in text


def test_render_finished_match_uses_approved_visual_style():
    text = render_guild_match_finished(
        champion_name="女仆公馆队",
        team1_score=2,
        team2_score=1,
        series_lines=("第1场：4 : 2", "第2场：3 : 4", "第3场：4 : 1"),
    )

    assert text.startswith("━━━━━━━━━━━━━━\n🏆 公会赛结束")
    assert "👑 冠军：女仆公馆队" in text
    assert "📊 最终大比分：2 : 1" in text
    assert "⚔️ 第1场：4 : 2" in text
    assert text.endswith("━━━━━━━━━━━━━━")
