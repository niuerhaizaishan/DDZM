from dzmm_bot.core.ai_mentions import ai_mention_content


def test_ai_trigger_matches_multiple_configured_prefixes_with_boundaries():
    triggers = ("@总监事", "/总监事", "/饭饭")

    assert ai_mention_content("@总监事 今天好吗", triggers) == "今天好吗"
    assert ai_mention_content("/总监事 今天好吗", triggers) == "今天好吗"
    assert ai_mention_content("/饭饭 今天好吗", triggers) == "今天好吗"
    assert ai_mention_content("/饭饭堂 今天好吗", triggers) is None
    assert ai_mention_content("/饭饭", triggers) is None


def test_ai_trigger_prefers_the_longest_overlapping_prefix():
    assert (
        ai_mention_content("/饭饭 助手 今天好吗", ("/饭饭", "/饭饭 助手"))
        == "今天好吗"
    )


def test_ai_at_trigger_strips_the_platform_bot_label():
    assert (
        ai_mention_content("@总监事「Bot」 今天好吗", ("@总监事",))
        == "今天好吗"
    )


def test_ai_trigger_strips_the_platform_display_name_suffix():
    triggers = ("@饭饭", "/饭饭")

    assert (
        ai_mention_content("@饭饭（小狗青巫）总监给我炒俩菜", triggers)
        == "总监给我炒俩菜"
    )
    assert ai_mention_content("/饭饭（小狗青巫）.抱抱～", triggers) == ".抱抱～"
    assert ai_mention_content("/饭饭堂（小狗青巫）.抱抱～", triggers) is None
