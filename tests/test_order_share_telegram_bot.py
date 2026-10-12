"""Private share lookup: permissions, bounded SQL, existing URLs and no live sends."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
# The Telegram bot is a standalone module. Avoid importing services/__init__.py,
# which eagerly loads unrelated image/ERP modules not required for these tests.
SERVICES = types.ModuleType("services")
SERVICES.__path__ = [str(ROOT / "services")]
sys.modules["services"] = SERVICES
ACCESS_SPEC = importlib.util.spec_from_file_location(
    "services.order_share_telegram_access", ROOT / "services/order_share_telegram_access.py")
ACCESS = importlib.util.module_from_spec(ACCESS_SPEC)
ACCESS_SPEC.loader.exec_module(ACCESS)
SERVICES.order_share_telegram_access = ACCESS
sys.modules["services.order_share_telegram_access"] = ACCESS
SPEC = importlib.util.spec_from_file_location("share_bot_under_test", ROOT / "services/order_share_telegram_bot.py")
bot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bot)


def update(user=11, chat=11, kind="private", text="OSCAR", update_id=10):
    return {"update_id": update_id, "message": {
        "from": {"id": user, "is_bot": False},
        "chat": {"id": chat, "type": kind}, "text": text}}


class TelegramShareTests(unittest.TestCase):
    def setUp(self):
        self.environ = patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_ALLOWED_IDS": "11, 22"})
        self.environ.start()
        self.fake_bot = {"token": "test-only-credential", "enabled": True,
                         "plugin_key": "ORDER_SHARES", "webhook_secret": "test-secret", "bot_username": "OrderBot"}

    def tearDown(self):
        self.environ.stop()

    def test_only_real_private_sender_identity_is_accepted(self):
        self.assertEqual(bot._actor(update()), (11, 11, "OSCAR"))
        for value in [update(kind="group"), update(chat=-99), update(user=True, chat=True),
                      update(user="11", chat=11), {"callback_query": {}}, [], None]:
            self.assertIsNone(bot._actor(value))

    def test_default_deny_and_numeric_allowlist(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_ALLOWED_IDS": ""}):
            self.assertEqual(bot._allowed_ids(), set())
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_ALLOWED_IDS": "11,22; -1 username 0\n33"}):
            self.assertEqual(bot._allowed_ids(), {11, 22, 33})

    def test_unknown_sender_never_reads_shares(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", side_effect=AssertionError("customer data queried")), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 999, 999, "OSCAR")
        self.assertIn("管理员尚未设置", send.call_args.args[2])

    def test_id_returns_only_the_senders_id_even_before_authorization(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", side_effect=AssertionError("customer data queried")), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 999, 999, "/id")
        self.assertEqual(send.call_args.args[1], 999)
        self.assertEqual(send.call_args.args[2], "你的 Telegram ID：<code>999</code>")

    def test_help_unknown_command_and_blank_never_query_customer_tables(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", side_effect=AssertionError("customer data queried")), \
             patch.object(bot, "_send_reply") as send:
            for text in ["/start", "/help", "/links", "/delete OSCAR", ""]:
                bot._process("orders", 11, 11, text)
        self.assertEqual(send.call_count, 4)

    def test_bare_customer_name_and_command_use_same_lookup(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", return_value=[]) as lookup, \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 11, 11, "SERGIO CONDO COLQUE")
            bot._process("orders", 11, 11, "/links@OrderBot   SERGIO  CONDO COLQUE")
        self.assertEqual([call.args[0] for call in lookup.call_args_list],
                         ["SERGIO CONDO COLQUE", "SERGIO CONDO COLQUE"])
        self.assertIn("沒有找到", send.call_args.args[2])

    def test_full_name_is_clickable_with_single_compact_copy_button(self):
        original_name = "OSCAR <X>& " + "LONG NAME " * 8
        rows = [{"token_hash": "a" * 64, "customer_name": original_name,
                 "created_at": "2026-10-01", "expires_at": None}]
        with patch.object(bot, "_share_url", return_value="https://example.invalid/share/existing?a=1&b=2") as link:
            text, buttons = bot._search_reply("<query>", rows)
        link.assert_called_once_with(rows[0])
        self.assertIn("OSCAR &lt;X&gt;&amp; " + "LONG NAME " * 7, text)
        self.assertIn('href="https://example.invalid/share/existing?a=1&amp;b=2"', text)
        self.assertIn("&lt;query&gt;", text)
        self.assertIn("永久", text)
        self.assertEqual(buttons, [[{"text": "📋 複製連結", "copy_text": {
            "text": "https://example.invalid/share/existing?a=1&b=2"}}]])
        self.assertNotIn("複製連結", text)
        self.assertNotIn("打开 · ", text)
        self.assertNotIn("建立 01-10-2026", text)

    def test_result_text_bounded_and_numbered_copy_buttons(self):
        rows = [{"token_hash": "a" * 64, "customer_name": "<&" * 200, "created_at": "2026-10-01",
                 "expires_at": "2026-11-01"}] * 6
        with patch.object(bot, "_share_url", return_value="https://example.invalid/share/existing"):
            text, controls = bot._search_reply("query", rows)
        self.assertGreaterEqual(len(controls), 1)
        self.assertLessEqual(len(controls), 2)
        self.assertTrue(all(len(row) <= 4 for row in controls))
        self.assertEqual(controls[0][0]["text"], "📋 複製連結")
        self.assertEqual(controls[0][0]["copy_text"]["text"],
                         "https://example.invalid/share/existing")
        self.assertLess(len(text), 4096)
        self.assertIn("還有更多", text)

    def test_database_error_is_not_reported_as_no_matching_customers(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", side_effect=RuntimeError("private detail")), \
             patch.object(bot, "_send_reply") as send, patch.object(bot._LOG, "warning"):
            bot._process("orders", 11, 11, "OSCAR")
        self.assertIn("暂时无法读取", send.call_args.args[2])
        self.assertNotIn("private detail", send.call_args.args[2])

    def test_failed_delivery_never_exposes_token_in_exception(self):
        with patch.object(bot.requests, "post", side_effect=RuntimeError("https://api.telegram.org/botSECRET/sendMessage")):
            with self.assertRaisesRegex(RuntimeError, "could not be delivered") as caught:
                bot._send_reply("SECRET", 11, "text")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_delivery_uses_post_timeout_disabled_preview_and_native_copy(self):
        reply = Mock(status_code=200)
        reply.json.return_value = {"ok": True}
        controls = [[{"text": "复制", "copy_text": {"text": "https://example.invalid/share/a"}}]]
        with patch.object(bot.requests, "post", return_value=reply) as post:
            bot._send_reply("test-only", 11, "text", controls)
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], 11)
        self.assertTrue(post.call_args.kwargs["json"]["link_preview_options"]["is_disabled"])
        self.assertEqual(post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"], controls)

    def test_webhook_handler_returns_without_waiting_for_query_or_delivery(self):
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()
        def process(*args):
            entered.set();release.wait(2);ended.set()
        with bot._LOCK:
            bot._RECENT.clear()
        with patch.object(bot, "_current_bot_key", return_value="orders"), \
             patch.object(bot, "_process", side_effect=process) as work:
            before = time.monotonic()
            self.assertTrue(bot.handle_update(update(update_id=800)))
            self.assertLess(time.monotonic() - before, .2)
            self.assertTrue(entered.wait(1))
            self.assertTrue(bot.handle_update(update(update_id=800)))
            release.set();self.assertTrue(ended.wait(1))
            self.assertEqual(work.call_count, 1)

    def test_registration_is_an_extra_lazy_plugin_not_a_replacement(self):
        source = (ROOT / "blueprints/automation_hub/__init__.py").read_text()
        self.assertIn('"ADUANA"', source)
        self.assertIn('"ORDER_SHARES"', source)
        self.assertIn('"services.order_share_telegram_bot"', source)

    def test_disabled_other_plugin_or_secretless_bot_cannot_reply(self):
        hub = types.ModuleType("blueprints.automation_hub")
        hub.storage = Mock()
        with patch.dict(sys.modules, {"blueprints.automation_hub": hub}):
            for value in [None, {**self.fake_bot, "enabled": False},
                          {**self.fake_bot, "plugin_key": "ADUANA"},
                          {**self.fake_bot, "webhook_secret": ""}]:
                hub.storage.get_bot_by_key.return_value = value
                self.assertIsNone(bot._load_bot("orders"))

    def test_all_is_paginated_and_buttons_use_callback_without_leaking_secrets(self):
        rows = [
            {"token_hash": str(i), "customer_name": "CLIENT " + str(i),
             "created_at": "2026-10-01", "expires_at": None}
            for i in range(9)
        ]
        with patch.object(bot, "_share_url", side_effect=lambda row: "https://example.invalid/share/" + row["token_hash"]):
            text, buttons = bot._all_reply(1, rows)
        self.assertIn("第 1 頁", text)
        self.assertEqual(len(buttons), 3)  # Two short copy rows + navigation
        self.assertEqual([len(row) for row in buttons], [4, 4, 2])
        self.assertEqual(buttons[0][0]["text"], "📋1")
        self.assertEqual(buttons[0][0]["copy_text"]["text"], "https://example.invalid/share/0")
        self.assertEqual(buttons[1][3]["text"], "📋8")
        self.assertEqual(buttons[-1][0]["callback_data"], "order_shares:all:1")
        self.assertEqual(buttons[-1][1]["callback_data"], "order_shares:all:2")
        self.assertIn("1. <a href=", text)
        self.assertIn("8. <a href=", text)
        self.assertNotIn("9. <a href=", text)

        with patch.object(bot, "_share_url", side_effect=lambda row: "https://example.invalid/share/" + row["token_hash"]):
            _, buttons2 = bot._all_reply(2, rows[:3])
        self.assertEqual(buttons2[-1][0]["callback_data"], "order_shares:all:1")
        self.assertEqual(buttons2[-1][1]["callback_data"], "order_shares:all:1")
        self.assertEqual(buttons2[0][0]["text"], "📋9")
        self.assertIn("9. <a href=", _)

    def test_all_queries_only_after_authorization(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_all", return_value=[]) as lookup, \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 11, 11, "/all")
            lookup.assert_called_once_with(1)
            self.assertIn("沒有有效分享", send.call_args.args[2])

    def test_all_aliases_case_insensitive_and_chinese(self):
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_all", return_value=[]) as lookup, \
             patch.object(bot, "_send_reply") as send:
            for text in ("/all", "全部", "todo", "TODO", "ToDo", "todos", "ALL", "/todo",
                         "📋 全部客戶", "📋 全部客户", "全部客戶"):
                bot._process("orders", 11, 11, text)
            bot._process("orders", 11, 11, "/all 3")
        self.assertEqual(lookup.call_count, 12)
        self.assertEqual([c.args[0] for c in lookup.call_args_list], [1] * 11 + [3])
        self.assertEqual(send.call_count, 12)

    def test_company_group_does_not_reply_to_unrelated_chatter(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=True), \
             patch.object(bot, "_lookup_shares", return_value=[]) as lookup, \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 11, -100123456789, "大家午安")
            send.assert_not_called()
            bot._process("orders", 11, -100123456789, "/links nonexistent")
            self.assertEqual(send.call_count, 1)
            self.assertIn("没有找到", send.call_args.args[2])
            self.assertEqual(lookup.call_count, 2)

    def test_persistent_one_tap_keyboard_uses_existing_authorization(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=True), \
             patch.object(bot, "_send_reply") as send:
            for command in ("/start", "/menu", "菜單"):
                bot._process("orders", 11, -100123456789, command)
                self.assertTrue(send.call_args.kwargs.get("show_menu"))
                self.assertIn("快捷鍵盤", send.call_args.args[2])

        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}
        with patch.object(bot.requests, "post", return_value=response) as post:
            bot._send_reply("test-token", -100123456789, "選單", show_menu=True)
        payload = post.call_args.kwargs["json"]
        markup = payload["reply_markup"]
        self.assertTrue(markup["is_persistent"])
        self.assertFalse(markup["one_time_keyboard"])
        self.assertEqual(markup["keyboard"][0][0]["text"], "📋 全部客戶")
        self.assertNotIn("inline_keyboard", markup)

    def test_menu_access_denied_to_outsiders(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=False), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 99, -100123456789, "/menu")
        self.assertFalse(send.call_args.kwargs.get("show_menu", False))

    def test_customer_search_has_one_click_all_button(self):
        row = {"token_hash": "a" * 64, "customer_name": "SERGIO CONDO COLQUE",
               "created_at": "2026-10-01", "expires_at": None}
        with patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch.object(bot, "_lookup_shares", return_value=[row]), \
             patch.object(bot, "_share_url", return_value="https://example.invalid/share/sergio"), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 11, 11, "SERGIO")
        buttons = send.call_args.args[3]
        self.assertEqual(buttons[0][0]["text"], "📋 複製連結")
        self.assertEqual(buttons[0][0]["copy_text"]["text"], "https://example.invalid/share/sergio")
        self.assertEqual(buttons[-1][0]["callback_data"], "order_shares:all:1")

    def test_callback_pagination_private_and_authorized_group_only(self):
        def callback(user=11, chat=11, kind="private", data="order_shares:all:2"):
            return {"callback_query": {"id": "abc", "data": data,
                "from": {"id": user, "is_bot": False},
                "message": {"chat": {"id": chat, "type": kind}}}}
        self.assertEqual(bot._callback_actor(callback()), (11, 11, "/all 2", "abc"))
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}):
            self.assertEqual(
                bot._callback_actor(callback(chat=-100123456789, kind="supergroup")),
                (11, -100123456789, "/all 2", "abc"),
            )
            self.assertIsNone(bot._callback_actor(callback(chat=-100999999999, kind="supergroup")))
            self.assertIsNone(bot._callback_actor(callback(chat=-100123456789, kind="channel")))
            self.assertIsNone(bot._callback_actor(callback(data="order_shares:all:0")))
            self.assertIsNone(bot._callback_actor(callback(data="order_shares:all:10000")))
            self.assertIsNone(bot._callback_actor(callback(data="other:all:2")))

    def test_staff_group_messages_only_in_configured_group(self):
        staff_group = -100123456789
        allowed = update(user=11, chat=staff_group, kind="supergroup",
                         text="/all", update_id=904)
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": str(staff_group)}):
            self.assertEqual(bot._group_actor(allowed), (11, staff_group, "/all"))
            self.assertEqual(
                bot._group_actor(update(user=11, chat=staff_group,
                                        kind="supergroup", text="SERGIO")),
                (11, staff_group, "SERGIO"),
            )
            self.assertEqual(
                bot._group_actor(update(user=11, chat=staff_group, kind="supergroup",
                                        text="/all@XingwangOrderLinkBot")),
                (11, staff_group, "/all@XingwangOrderLinkBot"),
            )
            for wrong in [-100999999999, -100123456788]:
                self.assertIsNone(bot._group_actor(update(user=11, chat=wrong,
                                                        kind="supergroup", text="/all")))
            self.assertIsNone(bot._group_actor(update(user=11, chat=staff_group,
                                            kind="channel", text="/all")))
            from_bot = update(user=11, chat=staff_group, kind="supergroup", text="/all")
            from_bot["message"]["from"]["is_bot"] = True
            self.assertIsNone(bot._group_actor(from_bot))
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": ""}):
            self.assertIsNone(bot._group_actor(allowed))
            self.assertEqual(
                bot._group_actor(update(user=11, chat=staff_group,
                                        kind="supergroup", text="/groupid")),
                (11, staff_group, "/groupid"),
            )

    def test_group_can_search_all_and_customer_without_leaking_to_other_groups(self):
        group = -100123456789
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": str(group)}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=True) as member, \
             patch.object(bot, "_lookup_all", return_value=[]) as lookup_all, \
             patch.object(bot, "_lookup_shares", return_value=[]) as lookup_shares, \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 11, group, "/all")
            lookup_all.assert_called_once_with(1)
            self.assertEqual(send.call_args.args[1], group)
            bot._process("orders", 11, group, "SERGIO")
            lookup_shares.assert_called_once_with("SERGIO")
            self.assertEqual(send.call_args.args[1], group)
            self.assertEqual(member.call_count, 2)
            # Unmatched ordinary group messages stay silent to avoid chat spam.
            self.assertEqual(send.call_count, 1)
            bot._process("orders", 11, -100999999999, "/all")
            self.assertEqual(member.call_count, 2)
            self.assertEqual(send.call_count, 1)

    def test_group_unauthorized_sender_and_command_to_other_bot_are_silent(self):
        group = -100123456789
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": str(group)}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=False), \
             patch.object(bot, "_lookup_all", side_effect=AssertionError("private data leaked")), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 99, group, "/all")
            self.assertIn("私人群组", send.call_args.args[2])
            bot._process("orders", 99, group, "/all@OtherBot")
            self.assertEqual(send.call_count, 1)

    def test_private_group_members_only_and_no_company_passcodes(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", return_value=False) as member, \
             patch.object(bot, "_lookup_all", side_effect=AssertionError("not authorized")), \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 999, 999, "/all")
        member.assert_called_once_with("orders", 999, "test-only-credential")
        self.assertIn("私人群组", send.call_args.args[2])

    def test_removing_staff_rechecks_group_membership_on_every_query(self):
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"}), \
             patch.object(bot, "_load_bot", return_value=self.fake_bot), \
             patch("services.order_share_telegram_access.is_authorized", side_effect=[True, False]) as member, \
             patch.object(bot, "_lookup_all", return_value=[]) as lookup, \
             patch.object(bot, "_send_reply") as send:
            bot._process("orders", 999, 999, "/all")
            bot._process("orders", 999, 999, "/all")
        self.assertEqual(member.call_count, 2)
        lookup.assert_called_once_with(1)
        self.assertIn("私人群组", send.call_args.args[2])

    def test_existing_share_signer_resolves_to_original_share_without_db_writes(self):
        spec = importlib.util.spec_from_file_location("signer_under_test", ROOT / "services/order_share_links.py")
        signer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(signer)
        signer._KEY = b"test-signing-key-only-32-byte-long"
        token_hash = "a" * 64
        with patch.dict(sys.modules, {"services.order_share_links": signer}), \
             patch.object(bot, "_base_url", return_value="https://example.invalid"):
            url = bot._share_url({"token_hash": token_hash})
        self.assertEqual(signer.share_token_hash(url.rsplit("/", 1)[1]), token_hash)
        self.assertEqual(url, "https://example.invalid/share/" + signer.share_link_token(token_hash))

    def test_public_url_uses_config_not_incoming_host(self):
        hub = types.ModuleType("blueprints.automation_hub")
        hub.settings = types.SimpleNamespace(PUBLIC_BASE_URL="https://example.invalid/")
        with patch.dict(sys.modules, {"blueprints.automation_hub": hub}):
            self.assertEqual(bot._base_url(), "https://example.invalid")
            for value in ["http://example.invalid", "https://name:pass@example.invalid",
                          "https://example.invalid/?redirect=other", ""]:
                hub.settings.PUBLIC_BASE_URL = value
                with self.assertRaises(ValueError):
                    bot._base_url()


class PrivateGroupAccessTests(unittest.TestCase):
    def setUp(self):
        from services import order_share_telegram_access as access
        self.access = access
        self.group_env = patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "-100123456789"})
        self.group_env.start()

    def tearDown(self):
        self.group_env.stop()

    def test_group_id_only_accepts_negative_numeric_chat(self):
        self.assertEqual(self.access.group_id(), -100123456789)
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "12345"}):
            self.assertFalse(self.access.configured())
        with patch.dict(os.environ, {"ORDER_SHARE_TELEGRAM_GROUP_ID": "groupname"}):
            self.assertIsNone(self.access.group_id())

    def test_actual_telegram_membership_verified_no_local_password(self):
        for status, extra, expected in [
            ("member", {}, True),
            ("administrator", {}, True),
            ("creator", {}, True),
            ("restricted", {"is_member": True}, True),
            ("restricted", {"is_member": False}, False),
            ("left", {}, False),
            ("kicked", {}, False),
        ]:
            response = Mock(status_code=200)
            response.json.return_value = {"ok": True, "result": {"status": status, **extra}}
            with patch.object(self.access.requests, "post", return_value=response) as post:
                self.assertEqual(self.access.is_authorized("orders", 11, "test-token"), expected)
                self.assertEqual(post.call_args.kwargs["json"],
                                 {"chat_id": -100123456789, "user_id": 11})
                self.assertEqual(post.call_args.kwargs["timeout"], 8)

    def test_api_error_fails_closed_without_exposing_bot_token(self):
        with patch.object(self.access.requests, "post", side_effect=RuntimeError("test-token")):
            self.assertFalse(self.access.is_authorized("orders", 11, "test-token"))
        with patch.object(self.access.requests, "post", return_value=Mock(status_code=403)):
            self.assertFalse(self.access.is_authorized("orders", 11, "test-token"))
        self.assertFalse(self.access.is_authorized("orders", 0, "test-token"))


class ReadOnlyLookupTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("UTC_TIMESTAMP", 0, lambda: "2026-10-12 03:00:00")
        self.conn.executescript("""
          CREATE TABLE cloud_customers(customer_key TEXT,customer_name TEXT,active INTEGER);
          CREATE TABLE cloud_share_tokens(token_hash TEXT,customer_key TEXT,status TEXT,created_at TEXT,expires_at TEXT);
          INSERT INTO cloud_customers VALUES ('oscar','OSCAR LLANO',1),('inactive','OSCAR INACTIVE',0),('literal','ACME 100%_',1);
          INSERT INTO cloud_share_tokens VALUES
            ('active','oscar','active','2026-10-01',NULL),
            ('temporary','oscar','active','2026-10-01','2026-10-13 03:00:00'),
            ('expired','oscar','active','2026-10-01','2026-10-11 03:00:00'),
            ('revoked','oscar','revoked','2026-10-01',NULL),
            ('inactive','inactive','active','2026-10-01',NULL),
            ('literal','literal','active','2026-10-01',NULL);
        """)
        self.conn.execute("PRAGMA query_only=ON")
        self.statements = []
        self.conn.set_trace_callback(self.statements.append)
        self.wrapper = Mock()
        self.wrapper.close = Mock()
        self.database = types.ModuleType("database")
        self.database.get_db_connection = Mock(return_value=self.wrapper)
        self.database.get_cursor = lambda _: self.conn.cursor()
        self.database.get_row_dict = lambda row, _: dict(row)

    def tearDown(self):
        self.conn.close()

    def test_only_active_unexpired_customer_shares_and_one_select(self):
        with patch.dict(sys.modules, {"database": self.database}):
            rows = bot._lookup_shares("OsCaR")
        self.assertEqual({row["token_hash"] for row in rows}, {"active", "temporary"})
        self.assertEqual(len(self.statements), 1)
        self.assertTrue(self.statements[0].lstrip().upper().startswith("SELECT"))
        self.wrapper.close.assert_called_once()

    def test_query_wildcards_are_literal_and_sql_injection_is_not_executed(self):
        with patch.dict(sys.modules, {"database": self.database}):
            self.assertEqual([row["token_hash"] for row in bot._lookup_shares("100%_")], ["literal"])
            self.assertEqual(bot._lookup_shares("%' OR 1=1 --"), [])


    def test_keyword_search_word_order_and_partial_name(self):
        with patch.dict(sys.modules, {"database": self.database}):
            forward = bot._lookup_shares("OSCAR LLANO")
            backward = bot._lookup_shares("LLANO OSCAR")
            partial = bot._lookup_shares("OSCA")
        self.assertEqual([r["token_hash"] for r in forward],
                         [r["token_hash"] for r in backward])
        self.assertEqual({r["token_hash"] for r in partial}, {"active", "temporary"})

    def test_all_pages_are_readonly_and_exclude_expired_revoked_inactive(self):
        with patch.dict(sys.modules, {"database": self.database}):
            first = bot._lookup_all(1)
        self.assertEqual({r["token_hash"] for r in first}, {"active", "temporary", "literal"})
        self.assertEqual(len(self.statements), 1)
        self.assertTrue(self.statements[0].lstrip().upper().startswith("SELECT"))

if __name__ == "__main__":
    unittest.main()
