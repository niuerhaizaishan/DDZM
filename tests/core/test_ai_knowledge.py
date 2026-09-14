from dzmm_bot.core.ai_knowledge import (
    AIKnowledgeCard,
    route_ai_topics,
    select_knowledge_cards,
)


def test_api_topic_literal_matches_the_routing_topics():
    """API 的 Literal 曾经漏掉 performance / dark_market 等主题，导致列表接口 500。"""
    from typing import get_args

    from dzmm_bot.core.ai_knowledge import KNOWLEDGE_TOPICS
    from dzmm_bot.core.api_models import AIKnowledgeTopic

    assert set(get_args(AIKnowledgeTopic)) == set(KNOWLEDGE_TOPICS)


def card(topic, keywords, *, priority=100, enabled=True, title=None):
    return AIKnowledgeCard(
        topic=topic,
        title=title or topic,
        keywords=tuple(keywords),
        content=f"{topic} rules",
        enabled=enabled,
        priority=priority,
    )


def test_route_ai_topics_matches_multiple_relevant_topics():
    cards = (
        card("economy", ["金币", "赚钱"], priority=20),
        card("ranks", ["晋升"], priority=10),
    )

    assert route_ai_topics("我怎么赚金币然后申请晋升？", cards) == (
        "ranks",
        "economy",
    )


def test_route_ai_topics_uses_exact_command_aliases():
    assert route_ai_topics("/躲 是怎么玩的", ()) == ("hide_and_seek",)
    assert route_ai_topics("/答案 应该怎么发", ()) == ("memory_assessment",)
    assert route_ai_topics("蹦蹦数字炸弹怎么报数", ()) == ("number_bomb",)
    assert route_ai_topics("平均数炸弹怎么玩", ()) == ("number_bomb",)
    assert route_ai_topics("积分赛第七名扣几分", ()) == ("number_bomb",)
    assert route_ai_topics("/报数 29", ()) == ("number_bomb",)
    assert route_ai_topics("德州扑克怎么加注", ()) == ("texas_holdem",)
    assert route_ai_topics("/全下", ()) == ("texas_holdem",)
    assert route_ai_topics("暗网交易所怎么报价", ()) == ("dark_market",)
    assert route_ai_topics("/登陆暗网", ()) == ("dark_market",)
    assert route_ai_topics("怎么预约公演", ()) == ("performance",)
    assert route_ai_topics("/预约公演", ()) == ("performance",)
    assert route_ai_topics("我有你没有怎么玩", ()) == ("never_have_i_ever",)
    assert route_ai_topics("/我有你没有", ()) == ("never_have_i_ever",)
    assert route_ai_topics("公司双色球怎么机选", ()) == ("company_lottery",)
    assert route_ai_topics("彩票奖池和调节金是什么", ()) == ("company_lottery",)
    # 「购买」是商店的泛化关键词，带参数的购票指令会同时命中两个主题，这里只要求不丢彩票
    assert "company_lottery" in route_ai_topics("/购买彩票 03 07 09 10 + 05", ())
    assert route_ai_topics("/我的彩票", ()) == ("company_lottery",)


def test_routing_and_selection_are_normalized_bounded_and_deterministic():
    cards = tuple(
        card(
            "economy",
            [" Gold ", "gold"],
            priority=index,
            title=f"card-{index:02d}",
        )
        for index in range(8)
    ) + (card("ranks", ["晋升"], enabled=False),)

    assert route_ai_topics("  GOLD 怎么赚  ", cards) == ("economy",)
    assert len(select_knowledge_cards(("economy",), cards)) == 6
    assert [item.title for item in select_knowledge_cards(("economy",), cards)] == [
        f"card-{index:02d}" for index in range(6)
    ]
    assert select_knowledge_cards(("ranks",), cards) == ()
