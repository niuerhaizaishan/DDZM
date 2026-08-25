from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID


KNOWLEDGE_TOPICS = (
    "economy", "departments", "ranks", "shop", "checkin_activity",
    "random_events", "hide_and_seek", "memory_assessment", "undercover",
    "blame_bomb", "number_bomb", "texas_holdem", "dark_market", "commands_help", "player_activity",
)

TOPIC_COMMANDS = {
    "economy": ("/余额", "/我", "/打卡", "/商店"),
    "departments": ("/部门", "/加入部门", "/切换部门", "/部门申请列表", "/同意部门", "/全部同意部门", "/拒绝部门", "/全部拒绝部门"),
    "ranks": ("/职位", "/晋升", "/晋升申请列表", "/同意", "/全部同意", "/拒绝", "/全部拒绝"),
    "shop": (
        "/商店",
        "/购买",
        "/我的物品",
        "/使用",
        "/邀请参与",
        "/取消使用",
        "/同意使用",
        "/拒绝使用",
    ),
    "checkin_activity": ("/打卡", "/我"),
    "random_events": ("/加入", "/退出", "/打赏", "/投稿", "/我的投稿", "/撤回投稿"),
    "hide_and_seek": ("/摸鱼躲猫猫",),
    "memory_assessment": ("/记忆考核", "/加入", "/退出", "/继续", "/收手"),
    "undercover": ("/谁是卧底", "/加入", "/退出", "/开始投票", "/投票", "/继续", "/结束游戏"),
    "blame_bomb": ("/甩锅游戏", "/加入", "/退出", "/甩锅", "/结束游戏"),
    "number_bomb": ("/蹦蹦数字炸弹", "/加入", "/开始", "/报数", "/跳过", "/退出", "/继续", "/结束游戏"),
    "texas_holdem": ("/德州扑克", "/加入", "/开始", "/看牌", "/过牌", "/跟注", "/加注", "/全下", "/弃牌", "/退出"),
    "dark_market": ("/上架暗网", "/取消上架", "/确认", "/报价", "/登陆暗网", "/公开", "/不公开"),
    "commands_help": (),
    "player_activity": ("/我",),
}

_TOPIC_ALIASES = {
    "economy": ("金币", "摸鱼币", "赚钱", "收入", "余额"),
    "departments": ("部门", "加入部门", "切换部门", "部门申请"),
    "ranks": ("职位", "职级", "晋升", "升职"),
    "shop": ("商店", "商品", "物品", "购买"),
    "checkin_activity": ("打卡", "活跃", "全勤", "连续打卡"),
    "random_events": ("随机事件", "角色报名", "打赏"),
    "hide_and_seek": ("躲猫猫", "躲藏", "巡查"),
    "memory_assessment": ("记忆考核", "答案", "收手", "对战"),
    "undercover": ("谁是卧底", "卧底", "白板", "投票"),
    "blame_bomb": ("甩锅", "事故卡", "关键词"),
    "number_bomb": (
        "蹦蹦数字炸弹", "平均数炸弹", "积分赛", "累计积分", "第七名",
        "报数", "真心话", "大冒险",
    ),
    "texas_holdem": ("德州扑克", "德州", "盲注", "跟注", "加注", "全下", "弃牌"),
    "dark_market": ("暗网交易所", "暗网", "上架暗网", "报价", "流拍"),
    "commands_help": ("指令", "命令", "帮助", "怎么操作"),
    "player_activity": ("战绩", "玩过", "赢过", "输了", "参加过"),
}

_COMMAND_ALIASES = {
    "/开始摸鱼躲藏": "hide_and_seek", "/躲": "hide_and_seek",
    "/答案": "memory_assessment",
}
for _topic, _commands in TOPIC_COMMANDS.items():
    for _command in _commands:
        _COMMAND_ALIASES.setdefault(_command, _topic)


@dataclass(frozen=True)
class AIKnowledgeCard:
    topic: str
    title: str
    keywords: tuple[str, ...]
    content: str
    enabled: bool
    priority: int
    id: UUID | None = None


@dataclass(frozen=True)
class AIAuthoritativeContext:
    topics: tuple[str, ...]
    cards_text: str
    live_facts_text: str
    commands_text: str
    has_authoritative_source: bool


def route_ai_topics(
    question: str, cards: Sequence[AIKnowledgeCard]
) -> tuple[str, ...]:
    normalized = question.strip().casefold()
    matched: set[str] = set()
    priorities = {topic: 10001 for topic in KNOWLEDGE_TOPICS}
    for card in cards:
        if not card.enabled or card.topic not in priorities:
            continue
        keywords = {keyword.strip().casefold() for keyword in card.keywords if keyword.strip()}
        if any(keyword in normalized for keyword in keywords):
            matched.add(card.topic)
            priorities[card.topic] = min(priorities[card.topic], card.priority)
    for topic, aliases in _TOPIC_ALIASES.items():
        if any(alias.casefold() in normalized for alias in aliases):
            matched.add(topic)
    command_token = normalized.split(maxsplit=1)[0] if normalized.startswith("/") else ""
    command_topic = _COMMAND_ALIASES.get(command_token)
    if command_topic:
        matched.add(command_topic)
    topic_order = {topic: index for index, topic in enumerate(KNOWLEDGE_TOPICS)}
    return tuple(sorted(matched, key=lambda topic: (priorities[topic], topic_order[topic])))


def select_knowledge_cards(
    topics: Sequence[str],
    cards: Sequence[AIKnowledgeCard],
    *,
    limit: int = 6,
) -> tuple[AIKnowledgeCard, ...]:
    selected_topics = set(topics)
    selected = [
        card for card in cards
        if card.enabled and card.topic in selected_topics
    ]
    return tuple(sorted(selected, key=lambda card: (card.priority, card.title, str(card.id or "")))[:limit])
