# -*- coding: utf-8 -*-
"""Тесты MAX-транспорта: клиент API, клавиатуры, парсинг и роутинг update.

Запуск:  python -m unittest discover -s tests -v
"""

import asyncio
import os
import tempfile

import aiohttp
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, mock

# Изолируем БД до импорта модуля (как в test_schedule_bot.py).
_TEST_DATA = Path(tempfile.mkdtemp(prefix="max_transport_test_"))
os.environ.setdefault("DATA_DIR", str(_TEST_DATA))
os.environ.setdefault("CHECK_INTERVAL", "300")

import bot as botmod  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def make_bot():
    """Настоящий Bot с заглушенным сетевым слоем."""
    bot = botmod.Bot(token="test-token")
    bot._api = mock.AsyncMock()
    bot._throttle = mock.AsyncMock()
    return bot


def message_update(chat_id=100, user_id=200, text="/today",
                   chat_type="dialog", mid="mid-1"):
    return {
        "update_type": "message_created",
        "timestamp": 1700000000000,
        "message": {
            "sender": {
                "user_id": user_id, "first_name": "Иван",
                "last_name": "", "username": "", "is_bot": False,
            },
            "recipient": {
                "chat_id": chat_id, "chat_type": chat_type,
                "user_id": user_id,
            },
            "timestamp": 1700000000000,
            "body": {"mid": mid, "seq": 1, "text": text},
        },
    }


def callback_update(payload="today", chat_id=100, user_id=200,
                    callback_id="cb-1", with_message=True):
    update = {
        "update_type": "message_callback",
        "timestamp": 1700000000000,
        "callback": {
            "timestamp": 1700000000000,
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "first_name": "Иван",
                     "is_bot": False},
        },
    }
    if with_message:
        update["message"] = message_update(
            chat_id=chat_id, user_id=user_id, text="старое",
        )["message"]
    else:
        update["message"] = None
    return update


class FakePostCM:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class FakeUploadResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text


class TransportMixin:
    def tearDown(self):
        with botmod.db_connect() as conn:
            conn.execute("DELETE FROM subscribers")
            conn.execute("DELETE FROM rate_limit_state")
            conn.execute("DELETE FROM schedule_state")
            conn.execute("DELETE FROM schedule_notifications")
            conn.execute("DELETE FROM lesson_history")
            conn.execute("DELETE FROM subjects")


class TestHelpers(TestCase):
    def test_as_attachment_list(self):
        self.assertIsNone(botmod._as_attachment_list(None))
        kb = botmod.main_keyboard(False)
        self.assertEqual(botmod._as_attachment_list(kb), kb)
        single = {"type": "inline_keyboard", "payload": {}}
        self.assertEqual(botmod._as_attachment_list(single), [single])
        self.assertIsNone(botmod._as_attachment_list("nope"))

    def test_clip_text(self):
        self.assertIsNone(botmod._clip_text(None))
        self.assertEqual(botmod._clip_text("abc"), "abc")
        long = "x" * 5000
        clipped = botmod._clip_text(long)
        self.assertEqual(len(clipped), botmod.MAX_TEXT_LIMIT)
        self.assertTrue(clipped.endswith("…"))

    def test_resolve_photo_path(self):
        self.assertEqual(
            botmod._resolve_photo_path(Path("/tmp/a.png")),
            Path("/tmp/a.png"),
        )
        self.assertEqual(
            botmod._resolve_photo_path("/tmp/b.png"), Path("/tmp/b.png")
        )
        holder = SimpleNamespace(path="/tmp/c.png")
        self.assertEqual(
            botmod._resolve_photo_path(holder), Path("/tmp/c.png")
        )

    def test_is_group_chat(self):
        self.assertTrue(botmod._is_group_chat(SimpleNamespace(type="chat")))
        self.assertTrue(botmod._is_group_chat(SimpleNamespace(type="channel")))
        self.assertTrue(botmod._is_group_chat(SimpleNamespace(type="group")))
        self.assertFalse(botmod._is_group_chat(SimpleNamespace(type="dialog")))
        self.assertFalse(botmod._is_group_chat(SimpleNamespace(type="private")))
        self.assertFalse(botmod._is_group_chat(SimpleNamespace(type="")))


class TestKeyboards(TestCase):
    def test_main_keyboard_shape(self):
        kb = botmod.main_keyboard(False)
        self.assertEqual(len(kb), 1)
        self.assertEqual(kb[0]["type"], "inline_keyboard")
        rows = kb[0]["payload"]["buttons"]
        self.assertEqual(len(rows), 3)
        payloads = [b["payload"] for row in rows for b in row]
        self.assertEqual(
            payloads,
            ["today", "schedule", "subscribe", "status", "date", "help"],
        )
        for row in rows:
            for button in row:
                self.assertEqual(button["type"], "callback")
                self.assertTrue(button["text"])

        kb_on = botmod.main_keyboard(True)
        rows_on = kb_on[0]["payload"]["buttons"]
        payloads_on = [b["payload"] for row in rows_on for b in row]
        self.assertIn("unsubscribe", payloads_on)
        self.assertNotIn("subscribe", payloads_on)

    def test_staff_keyboard_payloads(self):
        day = date(2026, 9, 7)
        kb = botmod.staff_keyboard(69, day)
        rows = kb[0]["payload"]["buttons"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 3)
        self.assertEqual(rows[0][0]["payload"], "staff:69:2026-09-06")
        self.assertEqual(rows[0][2]["payload"], "staff:69:2026-09-08")
        with self.assertRaises(ValueError):
            botmod.staff_keyboard(999999, day)

    def test_staff_choice_keyboard(self):
        from staff_directory import search_staff

        matches = search_staff("Аглиуллина")
        self.assertTrue(matches)
        kb = botmod.staff_choice_keyboard(matches, date(2026, 9, 7))
        rows = kb[0]["payload"]["buttons"]
        self.assertEqual(len(rows), len(matches))
        self.assertTrue(rows[0][0]["payload"].startswith("staff:"))


class TestCommandExtraction(TestCase):
    def test_extract_command(self):
        self.assertEqual(
            botmod._extract_command("/date 04.09.2026"),
            ("date", "04.09.2026"),
        )
        self.assertEqual(botmod._extract_command("/today"), ("today", ""))
        self.assertEqual(
            botmod._extract_command("/start@my_bot arg"), ("start", "arg")
        )
        self.assertEqual(botmod._extract_command("расписание"), (None, ""))
        self.assertEqual(botmod._extract_command(""), (None, ""))
        self.assertEqual(botmod._extract_command("/"), (None, ""))
        self.assertEqual(botmod._extract_command(None), (None, ""))


class TestParsing(TestCase):
    def test_parse_dialog_message(self):
        msg = botmod._parse_message_dict(
            make_bot(), message_update()["message"]
        )
        self.assertIsInstance(msg, botmod.MaxMessage)
        self.assertEqual(msg.chat.id, 100)
        self.assertEqual(msg.chat.type, "dialog")
        self.assertEqual(msg.from_user.id, 200)
        self.assertEqual(msg.from_user.first_name, "Иван")
        self.assertEqual(msg.text, "/today")
        self.assertEqual(msg.message_id, "mid-1")

    def test_parse_group_message(self):
        msg = botmod._parse_message_dict(
            make_bot(),
            message_update(chat_type="chat", text="расписание")["message"],
        )
        self.assertEqual(msg.chat.type, "chat")
        self.assertTrue(botmod._is_group_chat(msg.chat))

    def test_parse_channel_post_without_sender(self):
        raw = message_update(chat_type="channel", text="пост")["message"]
        raw["sender"] = {}
        msg = botmod._parse_message_dict(make_bot(), raw)
        self.assertIsNone(msg.from_user)
        self.assertEqual(msg.chat.id, 100)

    def test_parse_message_fallback_to_sender(self):
        raw = message_update()["message"]
        raw["recipient"] = {"chat_type": "dialog", "user_id": 200}
        msg = botmod._parse_message_dict(make_bot(), raw)
        self.assertEqual(msg.chat.id, 200)

    def test_parse_callback(self):
        cb = botmod._parse_callback(make_bot(), callback_update("staff:69:2026-09-07"))
        self.assertIsInstance(cb, botmod.MaxCallback)
        self.assertEqual(cb.data, "staff:69:2026-09-07")
        self.assertEqual(cb.payload, "staff:69:2026-09-07")
        self.assertEqual(cb.callback_id, "cb-1")
        self.assertEqual(cb.from_user.id, 200)
        self.assertEqual(cb.message.chat.id, 100)

    def test_parse_callback_broken(self):
        bad = callback_update("today")
        bad["callback"] = {}
        self.assertIsNone(botmod._parse_callback(make_bot(), bad))

    def test_parse_callback_without_message(self):
        cb = botmod._parse_callback(
            make_bot(), callback_update("today", with_message=False)
        )
        self.assertIsNotNone(cb)
        self.assertIsNone(cb.message)

    def test_parse_chat_update(self):
        msg = botmod._parse_chat_update(
            make_bot(),
            {"chat_id": 55, "user": {"user_id": 77, "first_name": "А"}},
            text="/start",
        )
        self.assertEqual(msg.chat.id, 55)
        self.assertEqual(msg.from_user.id, 77)
        self.assertEqual(msg.text, "/start")


class TestMessageShortcuts(TestCase):
    def test_answer_delegates(self):
        bot = make_bot()
        bot.send_message = mock.AsyncMock()
        msg = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5, type="dialog"), text="hi",
        )
        run(msg.answer("hello", reply_markup=botmod.main_keyboard(False)))
        bot.send_message.assert_awaited_once()
        _args, kwargs = bot.send_message.call_args
        self.assertEqual(kwargs["attachments"][0]["type"], "inline_keyboard")

    def test_answer_photo_delegates(self):
        bot = make_bot()
        bot.send_photo = mock.AsyncMock()
        msg = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5, type="dialog"),
        )
        run(msg.answer_photo("/tmp/x.png", caption="cap"))
        bot.send_photo.assert_awaited_once_with(
            5, photo="/tmp/x.png", caption="cap",
            user_id=None, reply_markup=None,
        )

    def test_callback_answer_acks(self):
        bot = make_bot()
        bot.answer_callback = mock.AsyncMock()
        cb = botmod.MaxCallback(bot=bot, data="today", callback_id="cb-9")
        run(cb.answer("ignored", show_alert=True))
        bot.answer_callback.assert_awaited_once_with("cb-9")

    def test_edit_photo_without_mid(self):
        bot = make_bot()
        msg = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5), message_id=None
        )
        self.assertFalse(run(msg.edit_photo("/tmp/x.png")))

    def test_edit_photo_success(self):
        bot = make_bot()
        bot._upload_image = mock.AsyncMock(return_value="tok-1")
        bot.edit_message = mock.AsyncMock()
        msg = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5), message_id="m-1"
        )
        self.assertTrue(run(msg.edit_photo("/tmp/x.png", caption="c")))
        _args, kwargs = bot.edit_message.call_args
        self.assertEqual(kwargs["attachments"][0]["type"], "image")
        self.assertEqual(
            kwargs["attachments"][0]["payload"]["token"], "tok-1"
        )

    def test_edit_photo_failure(self):
        bot = make_bot()
        bot._upload_image = mock.AsyncMock(
            side_effect=RuntimeError("upload down")
        )
        msg = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5), message_id="m-1"
        )
        self.assertFalse(run(msg.edit_photo("/tmp/x.png")))


class TestBotClient(TestCase):
    def test_send_message_request_shape(self):
        bot = make_bot()
        bot._api.return_value = {"message": {"body": {"mid": "m"}}}
        result = run(bot.send_message(5, "<b>hi</b>"))
        self.assertEqual(result, {"body": {"mid": "m"}})
        bot._api.assert_awaited_once()
        _args, kwargs = bot._api.call_args
        self.assertEqual(_args, ("POST", "/messages"))
        self.assertEqual(kwargs["params"], {"chat_id": 5})
        self.assertEqual(kwargs["json_body"]["text"], "<b>hi</b>")
        self.assertEqual(kwargs["json_body"]["format"], "html")

    def test_send_message_truncates(self):
        bot = make_bot()
        bot._api.return_value = {}
        run(bot.send_message(5, "y" * 5000))
        body = bot._api.call_args[1]["json_body"]
        self.assertEqual(len(body["text"]), botmod.MAX_TEXT_LIMIT)

    def test_send_message_user_fallback(self):
        bot = make_bot()
        bot._api.return_value = {}
        run(bot.send_message(None, "hi", user_id=7))
        params = bot._api.call_args[1]["params"]
        self.assertEqual(params, {"user_id": 7})

    def test_send_message_needs_target(self):
        bot = make_bot()
        with self.assertRaises(ValueError):
            run(bot.send_message(None, "hi"))

    def test_upload_image_top_level_token(self):
        bot = make_bot()
        bot._api.return_value = {"url": "https://iu.oneme.ru/upload"}
        response = FakeUploadResponse(200, '{"token": "T1"}')
        bot.session = SimpleNamespace(
            closed=False,
            post=mock.Mock(return_value=FakePostCM(response)),
        )
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(b"fake-png")
            tmp.flush()
            token = run(bot._upload_image(tmp.name))
        self.assertEqual(token, "T1")

    def test_upload_image_photos_shape(self):
        bot = make_bot()
        bot._api.return_value = {"url": "https://iu.oneme.ru/upload"}
        response = FakeUploadResponse(
            200, '{"photos": {"a": {"token": "P1"}}}'
        )
        bot.session = SimpleNamespace(
            closed=False,
            post=mock.Mock(return_value=FakePostCM(response)),
        )
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(b"fake-png")
            tmp.flush()
            token = run(bot._upload_image(tmp.name))
        self.assertEqual(token, "P1")

    def test_upload_image_no_token(self):
        bot = make_bot()
        bot._api.return_value = {"url": "https://iu.oneme.ru/upload"}
        response = FakeUploadResponse(200, '{"photos": {}}')
        bot.session = SimpleNamespace(
            closed=False,
            post=mock.Mock(return_value=FakePostCM(response)),
        )
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            tmp.write(b"x")
            tmp.flush()
            with self.assertRaises(botmod.MaxApiError):
                run(bot._upload_image(tmp.name))

    def test_send_photo_retries_not_ready(self):
        bot = make_bot()
        bot._upload_image = mock.AsyncMock(return_value="tok")
        bot.send_message = mock.AsyncMock(
            side_effect=[
                botmod.MaxApiError(500, "attachment.not.ready", "wait"),
                {"body": {"mid": "m"}},
            ]
        )
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            result = run(bot.send_photo(9, photo="/tmp/x.png", caption="c"))
        self.assertEqual(result, {"body": {"mid": "m"}})
        self.assertEqual(bot.send_message.await_count, 2)
        attachments = bot.send_message.call_args[1]["attachments"]
        self.assertEqual(attachments[0]["type"], "image")
        self.assertEqual(attachments[0]["payload"]["token"], "tok")

    def test_send_photo_reraises_other_errors(self):
        bot = make_bot()
        bot._upload_image = mock.AsyncMock(return_value="tok")
        bot.send_message = mock.AsyncMock(
            side_effect=botmod.MaxApiError(500, "boom", "boom")
        )
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            with self.assertRaises(botmod.MaxApiError):
                run(bot.send_photo(9, photo="/tmp/x.png"))

    def test_answer_callback_ack(self):
        bot = make_bot()
        bot._api.return_value = {"success": True}
        run(bot.answer_callback("cb-1"))
        _args, kwargs = bot._api.call_args
        self.assertEqual(_args, ("POST", "/answers"))
        self.assertEqual(kwargs["params"], {"callback_id": "cb-1"})
        self.assertEqual(kwargs["json_body"], {})

    def test_get_chat_admins_parsing(self):
        bot = make_bot()
        bot._api.return_value = {
            "members": [
                {"user_id": 1},
                {"user": {"user_id": 2}},
                {"user_id": "bad"},
                "junk",
            ]
        }
        self.assertEqual(run(bot.get_chat_admins(10)), {1, 2})

    def test_get_chat_failure_returns_empty(self):
        bot = make_bot()
        bot._api.side_effect = botmod.MaxApiError(404, "not_found", "x")
        self.assertEqual(run(bot.get_chat(10)), {})

    def test_set_commands_shape(self):
        bot = make_bot()
        bot._api.return_value = {}
        run(bot.set_commands([{"name": "today", "description": "d"}]))
        _args, kwargs = bot._api.call_args
        self.assertEqual(_args, ("PATCH", "/me/commands"))
        self.assertEqual(
            kwargs["json_body"],
            {"commands": [{"name": "today", "description": "d"}]},
        )


class TestAdminAndRate(TransportMixin, TestCase):
    def test_private_chat_is_admin(self):
        msg = SimpleNamespace(
            chat=botmod.MaxChat(id=1, type="dialog"),
            from_user=botmod.MaxUser(id=2),
            bot=make_bot(),
        )
        self.assertTrue(run(botmod._is_group_admin(msg)))

    def test_group_admin_check(self):
        bot = make_bot()
        bot.get_chat_admins = mock.AsyncMock(return_value={2, 3})
        msg = SimpleNamespace(
            chat=botmod.MaxChat(id=10, type="chat"),
            from_user=botmod.MaxUser(id=2),
            bot=bot,
        )
        self.assertTrue(run(botmod._is_group_admin(msg)))
        msg.from_user = botmod.MaxUser(id=99)
        self.assertFalse(run(botmod._is_group_admin(msg)))

    def test_group_admin_api_error_allows(self):
        bot = make_bot()
        bot.get_chat_admins = mock.AsyncMock(
            side_effect=botmod.MaxApiError(403, "forbidden", "x")
        )
        msg = SimpleNamespace(
            chat=botmod.MaxChat(id=10, type="chat"),
            from_user=botmod.MaxUser(id=99),
            bot=bot,
        )
        self.assertTrue(run(botmod._is_group_admin(msg)))

    def test_rate_allow_ok(self):
        target = SimpleNamespace(from_user=SimpleNamespace(id=700001))
        with botmod.db_connect() as conn:
            conn.execute(
                "DELETE FROM rate_limit_state WHERE user_id = 700001"
            )
        self.assertTrue(run(botmod._rate_allow(target)))

    def test_rate_allow_blocked_with_warning(self):
        target = SimpleNamespace(
            from_user=SimpleNamespace(id=700002),
            answer=mock.AsyncMock(),
        )
        decision = botmod.RateLimitDecision(False, warning=True)
        with mock.patch.object(
            botmod, "check_rate_limit", return_value=decision
        ):
            self.assertFalse(run(botmod._rate_allow(target)))
        target.answer.assert_awaited_once_with(botmod.SPAM_WARNING_TEXT)

    def test_rate_allow_blocked_quiet(self):
        target = SimpleNamespace(
            from_user=SimpleNamespace(id=700003),
            answer=mock.AsyncMock(),
        )
        decision = botmod.RateLimitDecision(False, warning=False)
        with mock.patch.object(
            botmod, "check_rate_limit", return_value=decision
        ):
            self.assertFalse(run(botmod._rate_allow(target)))
        target.answer.assert_not_awaited()

    def test_send_rate_warning_callback(self):
        bot = make_bot()
        bot.answer_callback = mock.AsyncMock()
        bot.send_message = mock.AsyncMock()
        message = botmod.MaxMessage(
            bot=bot, chat=botmod.MaxChat(id=5), text="x"
        )
        callback = botmod.MaxCallback(
            bot=bot, data="today", callback_id="cb-1", message=message
        )
        run(botmod._send_rate_warning(callback))
        bot.answer_callback.assert_awaited_once_with("cb-1")
        bot.send_message.assert_awaited_once()
        _args, kwargs = bot.send_message.call_args
        self.assertIn("Слишком много", _args[1])


class TestRouting(TransportMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.bot = make_bot()
        self.bot.send_message = mock.AsyncMock(
            return_value={"body": {"mid": "m"}}
        )
        self.bot.send_photo = mock.AsyncMock()
        self.bot.answer_callback = mock.AsyncMock()
        self.bot.get_chat = mock.AsyncMock(return_value={})
        self.bot.get_chat_admins = mock.AsyncMock(return_value=set())

    def test_today_command_routed(self):
        with mock.patch.object(
            botmod, "_handle_today", new=mock.AsyncMock()
        ) as handler:
            run(botmod.handle_update(self.bot, message_update(text="/today")))
        handler.assert_awaited_once()
        message = handler.call_args[0][0]
        self.assertEqual(message.text, "/today")
        self.assertEqual(message.chat.id, 100)

    def test_unknown_command_falls_to_text_handler(self):
        with mock.patch.object(
            botmod, "cmd_text_schedule", new=mock.AsyncMock()
        ) as handler:
            run(botmod.handle_update(self.bot, message_update(text="/nope")))
        handler.assert_awaited_once()

    def test_plain_text_routed(self):
        with mock.patch.object(
            botmod, "cmd_text_schedule", new=mock.AsyncMock()
        ) as handler:
            run(
                botmod.handle_update(
                    self.bot, message_update(text="расписание")
                )
            )
        handler.assert_awaited_once()

    def test_greeting_text_is_silent(self):
        run(botmod.handle_update(self.bot, message_update(text="привет")))
        self.bot.send_message.assert_not_awaited()
        self.bot.send_photo.assert_not_awaited()

    def test_bot_messages_ignored(self):
        update = message_update(text="/today")
        update["message"]["sender"]["is_bot"] = True
        with mock.patch.object(
            botmod, "_handle_today", new=mock.AsyncMock()
        ) as handler:
            run(botmod.handle_update(self.bot, update))
        handler.assert_not_awaited()

    def test_callback_today(self):
        with mock.patch.object(
            botmod, "_handle_today", new=mock.AsyncMock()
        ) as handler:
            run(botmod.handle_update(self.bot, callback_update("today")))
        handler.assert_awaited_once()
        self.bot.answer_callback.assert_awaited_once_with("cb-1")

    def test_callback_unknown_payload_only_acks(self):
        run(botmod.handle_update(self.bot, callback_update("zzz-unknown")))
        self.bot.answer_callback.assert_awaited_once_with("cb-1")
        self.bot.send_message.assert_not_awaited()

    def test_callback_without_message_only_acks(self):
        run(
            botmod.handle_update(
                self.bot, callback_update("today", with_message=False)
            )
        )
        self.bot.answer_callback.assert_awaited_once_with("cb-1")
        self.bot.send_message.assert_not_awaited()

    def test_bot_started_shows_help(self):
        update = {
            "update_type": "bot_started",
            "timestamp": 1,
            "chat_id": 50,
            "user": {"user_id": 60, "first_name": "А", "is_bot": False},
        }
        run(botmod.handle_update(self.bot, update))
        self.bot.send_message.assert_awaited_once()
        _args, _kwargs = self.bot.send_message.call_args
        self.assertEqual(_args[0], 50)
        self.assertIn(botmod.GROUP_NAME, _args[1])

    def test_bot_added_greeting_and_removed_unsubscribe(self):
        added = {
            "update_type": "bot_added",
            "timestamp": 1,
            "chat_id": 701001,
            "user": {"user_id": 5, "first_name": "А"},
            "is_channel": False,
        }
        run(botmod.handle_update(self.bot, added))
        self.bot.send_message.assert_awaited_once()
        self.assertIn(
            botmod.GROUP_NAME, self.bot.send_message.call_args[0][1]
        )

        self.assertTrue(botmod.subscribe_user(701001, chat_type="chat"))
        removed = {
            "update_type": "bot_removed",
            "timestamp": 2,
            "chat_id": 701001,
            "user": {"user_id": 5},
            "is_channel": False,
        }
        run(botmod.handle_update(self.bot, removed))
        self.assertIsNone(botmod.subscriber_info(701001))

    def test_subscribe_enriches_group_title(self):
        self.bot.get_chat = mock.AsyncMock(
            return_value={"title": "ЭС7-24 чат"}
        )
        self.bot.get_chat_admins = mock.AsyncMock(return_value={200})
        update = message_update(
            chat_id=702001, user_id=200, text="/subscribe", chat_type="chat"
        )
        run(botmod.handle_update(self.bot, update))
        self.assertIsNotNone(botmod.subscriber_info(702001))
        with botmod.db_connect() as conn:
            row = conn.execute(
                "SELECT title FROM subscribers WHERE user_id = 702001"
            ).fetchone()
        self.assertEqual(row["title"], "ЭС7-24 чат")

    def test_unknown_update_ignored(self):
        run(
            botmod.handle_update(
                self.bot, {"update_type": "chat_title_changed"}
            )
        )
        self.bot.send_message.assert_not_awaited()

    def test_broken_update_does_not_raise(self):
        run(botmod.handle_update(self.bot, {}))
        run(botmod.handle_update(self.bot, {"update_type": "message_created"}))
        run(botmod.handle_update(self.bot, None))


class TestWebhookTarget(TestCase):
    def test_empty(self):
        with mock.patch.object(botmod, "MAX_WEBHOOK_URL", ""), \
             mock.patch.object(botmod, "MAX_WEBHOOK_PATH", "/max/webhook"):
            self.assertEqual(
                botmod._webhook_target(), ("", "/max/webhook")
            )

    def test_host_only_appends_path(self):
        with mock.patch.object(botmod, "MAX_WEBHOOK_URL", "https://bot.example.com"), \
             mock.patch.object(botmod, "MAX_WEBHOOK_PATH", "/max/webhook"):
            self.assertEqual(
                botmod._webhook_target(),
                ("https://bot.example.com/max/webhook", "/max/webhook"),
            )

    def test_full_url_kept(self):
        with mock.patch.object(
            botmod, "MAX_WEBHOOK_URL", "https://bot.example.com/hook123"
        ), mock.patch.object(botmod, "MAX_WEBHOOK_PATH", "/max/webhook"):
            self.assertEqual(
                botmod._webhook_target(),
                ("https://bot.example.com/hook123", "/hook123"),
            )


class TestTodayEndToEnd(TransportMixin, TestCase):
    """Полный путь /today: fetch -> PNG -> upload -> POST /messages."""

    def test_today_sends_rendered_image(self):
        from datetime import date as date_cls

        day = botmod.get_today()
        schedule = botmod.Schedule(
            date=day,
            group=botmod.GROUP_NAME,
            lessons=[
                botmod.Lesson(
                    pair="I", time="08:30 - 09:50", subject="Математика",
                    teacher="Иванов И.И.", room="УК107",
                    start="08:30", end="09:50",
                )
            ],
        )
        sent = []

        async def fake_api(method, path, *, params=None, json_body=None):
            if path == "/uploads":
                return {"url": "https://iu.oneme.ru/upload"}
            if path == "/messages":
                sent.append((params, json_body))
                return {"message": {"body": {"mid": "m1"}}}
            raise AssertionError(f"unexpected API call: {path}")

        bot = make_bot()
        bot._api = fake_api
        response = FakeUploadResponse(200, '{"token": "IMG-TOKEN"}')
        bot.session = SimpleNamespace(
            closed=False,
            post=mock.Mock(return_value=FakePostCM(response)),
        )

        images_before = set(botmod.IMAGE_DIR.glob("*.png"))
        with mock.patch.object(
            botmod, "get_schedule", new=mock.AsyncMock(return_value=schedule)
        ), mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(
                botmod.handle_update(
                    bot, message_update(text="/today", chat_id=703001)
                )
            )

        self.assertEqual(len(sent), 1)
        params, body = sent[0]
        self.assertEqual(params, {"chat_id": 703001})
        # Предмет рисуется внутри PNG; caption — только шапка.
        attachments = body["attachments"]
        self.assertEqual(attachments[0]["type"], "image")
        self.assertEqual(attachments[0]["payload"]["token"], "IMG-TOKEN")
        self.assertIn(botmod.GROUP_NAME, body["text"])
        self.assertIn("Занятий: 1", body["text"])
        # Временный PNG удалён после отправки.
        images_after = set(botmod.IMAGE_DIR.glob("*.png"))
        self.assertEqual(images_after - images_before, set())


class TestWebhookServer(TransportMixin, TestCase):
    """Настоящий aiohttp webhook-сервер на свободном порту."""

    def _free_port(self):
        import socket

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _serve_and_post(self, bot, port, secret, posts):
        async def scenario():
            seen = []

            async def fake_handle(_bot, update):
                seen.append(update)

            with mock.patch.object(
                botmod, "MAX_WEBHOOK_URL", "https://bot.example.com"
            ), mock.patch.object(
                botmod, "MAX_WEBHOOK_PATH", "/max/webhook"
            ), mock.patch.object(
                botmod, "MAX_WEBHOOK_SECRET", secret
            ), mock.patch.object(
                botmod, "PORT", port
            ), mock.patch.object(
                botmod, "handle_update", new=fake_handle
            ):
                task = asyncio.create_task(botmod._run_webhook(bot))
                await asyncio.sleep(0.6)
                try:
                    async with aiohttp.ClientSession() as session:
                        results = []
                        for path, json_body, headers in posts:
                            async with session.post(
                                f"http://127.0.0.1:{port}{path}",
                                json=json_body,
                                headers=headers or {},
                            ) as response:
                                results.append(response.status)
                        async with session.get(
                            f"http://127.0.0.1:{port}/health"
                        ) as response:
                            health = (response.status, await response.text())
                    await asyncio.sleep(0.2)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            return results, health, seen

        return run(scenario())

    def test_webhook_receives_update(self):
        bot = make_bot()
        bot.subscribe_webhook = mock.AsyncMock()
        port = self._free_port()
        update = {"update_type": "bot_started", "chat_id": 1}
        results, health, seen = self._serve_and_post(
            bot, port, "", [("/max/webhook", update, None)]
        )
        self.assertEqual(results, [200])
        self.assertEqual(health, (200, "ok"))
        bot.subscribe_webhook.assert_awaited_once()
        _args, kwargs = bot.subscribe_webhook.call_args
        self.assertEqual(
            _args[0], "https://bot.example.com/max/webhook"
        )
        self.assertIn("message_created", kwargs["update_types"])
        self.assertEqual(seen, [update])

    def test_webhook_secret_enforced(self):
        bot = make_bot()
        bot.subscribe_webhook = mock.AsyncMock()
        port = self._free_port()
        update = {"update_type": "bot_started", "chat_id": 1}
        results, _health, seen = self._serve_and_post(
            bot,
            port,
            "s3cret-value",
            [
                ("/max/webhook", update, None),
                (
                    "/max/webhook",
                    update,
                    {"X-Max-Bot-Api-Secret": "wrong"},
                ),
                (
                    "/max/webhook",
                    update,
                    {"X-Max-Bot-Api-Secret": "s3cret-value"},
                ),
            ],
        )
        self.assertEqual(results, [403, 403, 200])
        self.assertEqual(seen, [update])

    def test_webhook_requires_https(self):
        bot = make_bot()
        bot.subscribe_webhook = mock.AsyncMock()
        with mock.patch.object(
            botmod, "MAX_WEBHOOK_URL", "http://bot.example.com"
        ):
            run(botmod._run_webhook(bot))
        bot.subscribe_webhook.assert_not_awaited()


if __name__ == "__main__":
    main()
