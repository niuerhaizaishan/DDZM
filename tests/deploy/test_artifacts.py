from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    inspect,
    text,
)


ROOT = Path(__file__).resolve().parents[2]


def test_number_bomb_migration_extends_runtime_schema(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'number-bomb.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    engine = create_engine(database_url)
    before_upgrade = MetaData()
    Table(
        "users",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("joined_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "command_reply_templates",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("command", String(32), nullable=False),
        Column("scenario", String(64), nullable=False),
        Column("template", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "inbound_messages",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("platform_message_id", String(255), nullable=False),
        Column("sender_platform_id", String(255), nullable=False),
        Column("content", Text, nullable=False),
        Column("received_at", DateTime(timezone=True), nullable=False),
        Column("status", String(32), nullable=False),
        Column("ai_memory_eligible", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "ai_activity_events",
        before_upgrade,
        Column("event_key", String(255), primary_key=True),
        Column("user_id", Uuid, nullable=False),
        Column("activity_type", String(48), nullable=False),
        Column("result", String(32), nullable=False),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "ai_knowledge_cards",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("topic", String(48), nullable=False),
        Column("title", String(128), nullable=False),
        Column("keywords", JSON, nullable=False),
        Column("content", Text, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("priority", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    Table(
        "memory_assessment_settings",
        before_upgrade,
        Column("id", Integer, primary_key=True),
    )
    Table(
        "memory_assessment_games",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
    )
    Table(
        "undercover_settings",
        before_upgrade,
        Column("id", Integer, primary_key=True),
        Column("vote_seconds", Integer, nullable=False, default=120),
        Column("whiteboard_win_remaining", Integer, nullable=False, default=3),
    )
    Table(
        "undercover_sessions",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
    )
    Table(
        "undercover_games",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("session_id", Uuid, nullable=False),
    )
    Table(
        "undercover_session_members",
        before_upgrade,
        Column("id", Uuid, primary_key=True),
        Column("session_id", Uuid, nullable=False),
        Column("user_id", Uuid, nullable=False),
    )
    before_upgrade.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO memory_assessment_settings (id) VALUES (1)"))
        connection.execute(
            text(
                "INSERT INTO undercover_settings "
                "(id, vote_seconds, whiteboard_win_remaining) "
                "VALUES (1, 120, 3)"
            )
        )
    command.stamp(config, "20260810_33")

    command.upgrade(config, "20260811_38")

    inspector = inspect(engine)
    assert {
        "number_bomb_settings",
        "number_bomb_games",
        "number_bomb_members",
        "number_bomb_rounds",
        "number_bomb_round_players",
        "red_packet_settings",
        "red_packets",
        "red_packet_shares",
        "red_packet_daily_starts",
        "employee_number_counters",
    } <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("inbound_messages")} >= {
        "source_type",
        "chatroom_id",
    }
    assert "detail" in {
        column["name"] for column in inspector.get_columns("ai_activity_events")
    }

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260811_38"
        assert connection.execute(
            text("SELECT inactivity_timeout_minutes FROM number_bomb_settings WHERE id = 1")
        ).scalar_one() == 10
        assert connection.execute(
            text(
                "SELECT enabled, signup_timeout_minutes, reminder_interval_seconds "
                "FROM number_bomb_settings WHERE id = 1"
            )
        ).one() == (1, 2, 15)
        assert connection.execute(
            text(
                "SELECT duel_signup_timeout_minutes "
                "FROM memory_assessment_settings WHERE id = 1"
            )
        ).scalar_one() == 2
        assert connection.execute(
            text(
                "SELECT signup_timeout_minutes "
                "FROM undercover_settings WHERE id = 1"
            )
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT title FROM ai_knowledge_cards WHERE topic = 'number_bomb'")
        ).scalar_one() == "蹦蹦数字炸弹"
        assert connection.execute(
            text(
                "SELECT expiry_minutes, empty_probability_percent "
                "FROM red_packet_settings WHERE id = 1"
            )
        ).one() == (10, 5)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_knowledge_cards
                    (id, topic, title, keywords, content, enabled, priority, created_at, updated_at)
                VALUES
                    (:id, 'number_bomb', '管理员自建数字玩法', :keywords, '自定义内容', 1, 1, :now, :now)
                """
            ),
            {
                "id": "11111111111111111111111111111111",
                "keywords": '["自定义"]',
                "now": "2026-08-10 12:00:00",
            },
        )

    command.downgrade(config, "20260810_33")

    with engine.connect() as connection:
        titles = connection.execute(
            text("SELECT title FROM ai_knowledge_cards WHERE topic = 'number_bomb'")
        ).scalars().all()
    assert titles == ["管理员自建数字玩法"]


def test_systemd_units_use_environment_factories_and_isolated_ports():
    core = (ROOT / "deploy/systemd/dzmm-core.service").read_text()
    admin = (ROOT / "deploy/systemd/dzmm-admin-web.service").read_text()
    worker = (ROOT / "deploy/systemd/dzmm-browser-worker.service").read_text()
    ai_worker = (ROOT / "deploy/systemd/dzmm-ai-worker.service").read_text()
    example_env = (ROOT / "deploy/env/dzmm.example.env").read_text()

    assert "dzmm_bot.core.app:create_app_from_environment --factory" in core
    assert "--host 127.0.0.1 --port 18120" in core
    assert "dzmm_bot.admin.app:create_app_from_environment --factory" in admin
    assert "--host 0.0.0.0 --port 18090" in admin
    assert "-m dzmm_bot.browser.main" in worker
    assert "-m dzmm_bot.ai.main" in ai_worker
    assert "dzmm-core.service" in ai_worker
    assert "Description=DZMM DeepSeek AI Worker" in ai_worker
    assert "DP_API_KEY=CHANGE_ME" in example_env
    assert "DZMM_BOT_ID=" in example_env
    assert "DZMM_DEEPSEEK_MODEL=deepseek-v4-flash" in example_env
    assert "DZMM_DEEPSEEK_BASE_URL=https://api.deepseek.com" in example_env
    assert "MINIMAX" not in (ai_worker + example_env).upper()
    assert "9222" not in core + admin + worker


def test_deployment_runs_migrations_with_the_private_environment():
    deploy = (ROOT / "deploy/scripts/deploy.sh").read_text()
    migration_env = (ROOT / "migrations/env.py").read_text()

    assert "source /etc/dzmm/dzmm.env" in deploy
    assert "cd /opt/dzmm/current" in deploy
    assert "alembic -c /opt/dzmm/current/alembic.ini upgrade head" in deploy
    assert 'os.environ.get("DZMM_DATABASE_URL")' in migration_env
    assert 'usage: deploy.sh RELEASE_DIRECTORY' in deploy
    assert 'rsync -a --delete --exclude .git --exclude .venv "$dzmm_release_dir/"' in deploy
    assert "chown -R dzmm:dzmm /opt/dzmm/current" in deploy
    assert "runuser -u dzmm -- /opt/dzmm/venv/bin/playwright install chromium" in deploy
    worker_stop = deploy.index(
        "systemctl stop dzmm-admin-web.service dzmm-browser-worker.service "
        "dzmm-ai-worker.service dzmm-ai-memory-worker.service"
    )
    core_restart = deploy.index("systemctl restart dzmm-core.service")
    core_health = deploy.index("curl -fsS http://127.0.0.1:18120/healthz")
    worker_restart = deploy.index(
        "systemctl restart dzmm-admin-web.service dzmm-browser-worker.service "
        "dzmm-ai-worker.service dzmm-ai-memory-worker.service"
    )
    assert worker_stop < core_restart < core_health < worker_restart


def test_deployment_starts_a_separate_ai_memory_worker():
    memory_worker = (
        ROOT / "deploy/systemd/dzmm-ai-memory-worker.service"
    ).read_text()
    deploy = (ROOT / "deploy/scripts/deploy.sh").read_text()

    assert "Description=DZMM DeepSeek AI Memory Worker" in memory_worker
    assert "-m dzmm_bot.ai.memory_main" in memory_worker
    assert "After=network-online.target dzmm-core.service" in memory_worker
    assert "dzmm-ai-memory-worker.service" in deploy
    assert "systemctl enable dzmm-ai-memory-worker.service" in deploy


def test_deployment_enables_the_main_ai_worker_at_boot():
    deploy = (ROOT / "deploy/scripts/deploy.sh").read_text()

    assert "systemctl enable dzmm-ai-worker.service" in deploy


def test_weekly_attendance_migration_preserves_custom_me_templates():
    migration = (ROOT / "migrations/versions/20260806_11_weekly_attendance.py").read_text()

    assert "weekly_attendance_settlements" in migration
    assert "连续打卡：{连续打卡天数} 天。" in migration


def test_hide_and_seek_migration_creates_game_tables():
    migration = (ROOT / "migrations/versions/20260806_13_hide_and_seek.py").read_text()

    assert 'down_revision: str | None = "20260806_12"' in migration
    assert "hide_and_seek_settings" in migration
    assert "hide_and_seek_scenes" in migration
    assert "hide_and_seek_daily_plays" in migration
    assert "hide_and_seek_games" in migration
    assert "ux_hide_and_seek_one_selecting_user" in migration


def test_hide_and_seek_command_migration_preserves_custom_templates():
    migration = (ROOT / "migrations/versions/20260806_14_hide_and_seek_commands.py").read_text()

    assert 'down_revision: str | None = "20260806_13"' in migration
    assert "old_started_template" in migration
    assert "old_found_template" in migration
    assert "/开始摸鱼躲藏" in migration


def test_hide_and_seek_penalty_timing_migration_preserves_custom_start_copy():
    migration = (ROOT / "migrations/versions/20260806_15_hide_and_seek_penalty_timing.py").read_text()

    assert 'down_revision: str | None = "20260806_14"' in migration
    assert "old_started_template" in migration
    assert "old_expired_template" in migration
    assert "开局不扣除" in migration


def test_hide_and_seek_two_round_patrol_migration_updates_default_templates_only():
    migration = (ROOT / "migrations/versions/20260806_16_hide_and_seek_two_round_patrol.py").read_text()

    assert 'down_revision: str | None = "20260806_15"' in migration
    assert "old_found_template" in migration
    assert 'new_found_template = "{巡查过程}' in migration


def test_ordered_multi_reply_migration_removes_single_reply_constraint():
    migration = (ROOT / "migrations/versions/20260806_17_ordered_multi_replies.py").read_text()

    assert 'down_revision: str | None = "20260806_16"' in migration
    assert "outbound_messages_inbound_message_id_key" in migration
    assert 'sa.Column("reply_index", sa.Integer()' in migration


def test_separate_patrol_template_migration_adds_first_round_scenarios():
    migration = (
        ROOT / "migrations/versions/20260806_18_hide_and_seek_patrol_reply_templates.py"
    ).read_text()

    assert 'down_revision: str | None = "20260806_17"' in migration
    assert '"first_round_missed"' in migration
    assert '"found_first_round"' in migration
    assert '"created_at"' in migration
    assert '"updated_at"' in migration


def test_memory_assessment_migration_creates_game_tables():
    migration = (ROOT / "migrations/versions/20260806_19_memory_assessment.py").read_text()

    assert 'down_revision: str | None = "20260806_18"' in migration
    assert "memory_assessment_settings" in migration
    assert "memory_assessment_level_rules" in migration
    assert "memory_assessment_daily_plays" in migration
    assert "memory_assessment_games" in migration
    assert "memory_assessment_participants" in migration
    assert "memory_assessment_rounds" in migration


def test_memory_assessment_recall_migration_links_rounds_to_outbound_messages():
    migration = (ROOT / "migrations/versions/20260806_20_memory_assessment_recall.py").read_text()

    assert 'down_revision: str | None = "20260806_19"' in migration
    assert '"count"' in migration
    assert "recall_after_seconds" in migration
    assert "outbound_message_id" in migration


def test_random_event_command_gate_migration_adds_safe_defaults():
    migration = (ROOT / "migrations/versions/20260807_21_random_event_command_gate.py").read_text()

    assert 'down_revision: str | None = "20260806_20"' in migration
    assert "signup_allowed_commands" in migration
    assert "in_progress_allowed_commands" in migration
    assert "blocked_message" in migration


def test_rank_department_command_migration_preserves_custom_me_template():
    migration = (
        ROOT / "migrations/versions/20260807_23_rank_department_commands.py"
    ).read_text()

    assert 'down_revision: str | None = "20260807_22"' in migration
    assert 'templates.c.template == old_me_template' in migration
    assert 'templates.c.template == new_me_template' in migration
    assert '"/晋升申请列表"' in migration
    assert '"/全部拒绝"' in migration
    assert '"enabled": True' in migration
    assert '"created_at": now' in migration


def test_department_approval_migration_creates_request_and_audit_tables():
    migration = (
        ROOT / "migrations/versions/20260807_24_department_approvals.py"
    ).read_text()

    assert 'down_revision: str | None = "20260807_23"' in migration
    assert "department_requests" in migration
    assert "department_approvals" in migration
    assert "ux_department_requests_pending_employee" in migration


def test_ai_knowledge_migration_seeds_cards_and_syntax():
    migration = (
        ROOT / "migrations/versions/20260810_32_ai_knowledge_cards.py"
    ).read_text()

    assert 'revision: str = "20260810_32"' in migration
    assert 'down_revision: str | None = "20260810_31"' in migration
    assert '"ai_knowledge_cards"' in migration
    assert '"syntax"' in migration
    assert '"金币与余额原则"' in migration
    assert '"/甩锅 玩家编号 甩锅理由"' in migration
