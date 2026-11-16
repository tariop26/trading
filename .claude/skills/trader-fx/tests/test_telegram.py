import _path  # noqa
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

import telegram

TOKEN = "123456:SECRET-token-value"
CHAT = "123456789"


class Fake:
    """An injected http_post that replays a list of (status, body) answers."""

    def __init__(self, *answers):
        self.answers, self.calls, self.sleeps = list(answers), [], []

    def post(self, url, payload, timeout):
        self.calls.append((url, payload, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def send(self, text="hello"):
        return telegram.send_message(TOKEN, CHAT, text, http_post=self.post, sleep=self.sleep)


class TestSend(unittest.TestCase):
    def test_success_returns_true_and_posts_the_message(self):
        f = Fake((200, '{"ok":true}'))
        self.assertEqual(f.send("Bonjour"), (True, None))
        url, payload, timeout = f.calls[0]
        self.assertEqual(url, "https://api.telegram.org/bot%s/sendMessage" % TOKEN)
        self.assertEqual(payload, {"chat_id": CHAT, "text": "Bonjour"})
        self.assertGreater(timeout, 0)
        self.assertEqual(f.sleeps, [])

    def test_payload_has_no_parse_mode_and_keeps_special_characters(self):
        f = Fake((200, "{}"))
        text = 'Core <CPI> & "m/m" <!-- x'
        f.send(text)
        self.assertEqual(set(f.calls[0][1]), {"chat_id", "text"})
        self.assertEqual(f.calls[0][1]["text"], text)

    def test_retry_once_on_429_with_the_retry_after_of_the_answer(self):
        f = Fake((429, '{"ok":false,"parameters":{"retry_after":7}}'), (200, "{}"))
        self.assertEqual(f.send(), (True, None))
        self.assertEqual((len(f.calls), f.sleeps), (2, [7]))

    def test_retry_after_is_capped_at_30_seconds_and_defaults_to_5(self):
        f = Fake((429, '{"parameters":{"retry_after":100}}'), (200, "{}"))
        f.send()
        self.assertEqual(f.sleeps, [30])
        for body in ("", "not json", '{"parameters":{"retry_after":"x"}}', '{"parameters":{"retry_after":-3}}'):
            f = Fake((429, body), (200, "{}"))
            f.send()
            self.assertEqual(f.sleeps, [5], body)

    def test_retry_once_on_500_then_gives_up(self):
        f = Fake((500, ""), (200, "{}"))
        self.assertEqual(f.send(), (True, None))
        self.assertEqual(f.sleeps, [5])
        f = Fake((502, ""), (503, ""))
        self.assertEqual(f.send(), (False, "HTTP 503"))
        self.assertEqual((len(f.calls), f.sleeps), (2, [5]))

    def test_a_second_429_is_final(self):
        f = Fake((429, "{}"), (429, "{}"))
        self.assertEqual(f.send(), (False, "HTTP 429"))
        self.assertEqual(len(f.calls), 2)

    def test_400_and_404_are_not_retried(self):
        for code in (400, 401, 404):
            f = Fake((code, '{"ok":false}'))
            self.assertEqual(f.send(), (False, "HTTP %d" % code))
            self.assertEqual((len(f.calls), f.sleeps), (1, []))


class TestNoRealIdentifiers(unittest.TestCase):
    def test_the_real_chat_id_is_not_in_the_tests(self):
        real = "5404" + "12883"               # built in two parts: this file must not contain it
        here = os.path.dirname(os.path.abspath(__file__))
        for name in os.listdir(here):
            if name.endswith(".py"):
                with open(os.path.join(here, name), encoding="utf-8") as f:
                    self.assertNotIn(real, f.read(), name)


class TestNoSecretLeaks(unittest.TestCase):
    def test_a_network_error_reason_has_no_token_or_url(self):
        f = Fake((0, "URLError"))
        ok, reason = f.send()
        self.assertFalse(ok)
        self.assertEqual(reason, "erreur réseau (URLError)")

    def test_an_exception_of_the_injected_post_is_reported_by_type_only(self):
        f = Fake(RuntimeError("boom https://api.telegram.org/bot%s/sendMessage" % TOKEN))
        ok, reason = f.send()
        self.assertEqual((ok, reason), (False, "erreur réseau (RuntimeError)"))
        self.assertNotIn("SECRET", reason)

    def test_the_default_transport_reports_url_errors_by_type_only(self):
        err = urllib.error.URLError("failed: https://api.telegram.org/bot%s/sendMessage" % TOKEN)
        with mock.patch.object(telegram.urllib.request, "urlopen", side_effect=err):
            ok, reason = telegram.send_message(TOKEN, CHAT, "x")
        self.assertEqual((ok, reason), (False, "erreur réseau (URLError)"))
        self.assertNotIn("SECRET", reason)

    def test_the_default_transport_reports_http_errors_by_code_only(self):
        err = urllib.error.HTTPError("https://api.telegram.org/bot%s/sendMessage" % TOKEN, 400,
                                     "Bad Request", {}, io.BytesIO(b'{"ok":false}'))
        with mock.patch.object(telegram.urllib.request, "urlopen", side_effect=err):
            ok, reason = telegram.send_message(TOKEN, CHAT, "x")
        self.assertEqual((ok, reason), (False, "HTTP 400"))
        self.assertNotIn("SECRET", reason)

    def test_the_default_transport_sends_json_and_reads_the_status(self):
        class Resp:
            status = 200

            def read(self):
                return b'{"ok":true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(telegram.urllib.request, "urlopen", return_value=Resp()) as m:
            self.assertEqual(telegram.send_message(TOKEN, CHAT, "é"), (True, None))
        req = m.call_args[0][0]
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"chat_id": CHAT, "text": "é"})
        self.assertEqual(req.get_header("Content-type"), "application/json")


if __name__ == "__main__":
    unittest.main()
