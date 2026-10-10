"""Тесты бота без реальной модели: python -m unittest discover -s .github/scripts -p "test_review.py"."""
import importlib.util
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("review", os.path.join(HERE, "review.py"))
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

SECRET = "SUPER-SECRET-KEY-123"


def make_diff(path, added=3, removed=0, binary=False):
    if binary:
        return f"diff --git a/{path} b/{path}\nindex 111..222 100644\nBinary files a/{path} and b/{path} differ\n"
    body = "".join(f"+line {i}\n" for i in range(added)) + "".join(f"-old {i}\n" for i in range(removed))
    return (f"diff --git a/{path} b/{path}\nindex 111..222 100644\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,{removed} +1,{added} @@\n{body}")


def run_bot(diff_text, env=None, json_out=False):
    """Запускает review.main на временных файлах, возвращает (код, текст комментария, stderr)."""
    with tempfile.TemporaryDirectory() as folder:
        diff_path, out_path = os.path.join(folder, "diff.txt"), os.path.join(folder, "review.md")
        json_path = os.path.join(folder, "review.json") if json_out else None
        with open(diff_path, "w", encoding="utf-8") as handle:
            handle.write(diff_text)
        argv = ["review.py", diff_path, out_path] + ([json_path] if json_path else [])
        clean_env = {"PATH": os.environ.get("PATH", ""), "REVIEW_FAST_RETRY": "1"}
        clean_env.update(env or {})
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, clean_env, clear=True), redirect_stderr(stderr):
            code = review.main(argv)
        with open(out_path, encoding="utf-8") as handle:
            body = handle.read()
        saved = None
        if json_path and os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as handle:
                saved = json.load(handle)
        return code, body, stderr.getvalue(), saved


class DiffFilterTest(unittest.TestCase):
    def test_ignored_and_binary_files_are_skipped(self):
        text = (make_diff("app/a.py", 2, 1) + make_diff("poetry.lock", 50) + make_diff("dist/bundle.js", 80)
                + make_diff("web/generated/api.py", 40) + make_diff("logo.png", binary=True)
                + make_diff("data.bin", binary=True))
        kept, skipped = review.filter_files(review.parse_diff(text))
        self.assertEqual([f["path"] for f in kept], ["app/a.py"])
        self.assertEqual({p for p, _ in skipped},
                         {"poetry.lock", "dist/bundle.js", "web/generated/api.py", "logo.png", "data.bin"})
        self.assertEqual((kept[0]["added"], kept[0]["removed"]), (2, 1))

    def test_removed_line_starting_with_dashes_is_counted(self):
        text = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,1 @@\n"
                "--- old comment\n+new\n context\n")
        files = review.parse_diff(text)
        self.assertEqual((files[0]["added"], files[0]["removed"]), (1, 1))


class ThresholdTest(unittest.TestCase):
    def test_big_diff_skips_model(self):
        diff = make_diff("app/big.py", 600)
        with mock.patch.object(review, "ask_model", side_effect=AssertionError("модель не должна вызываться")):
            code, body, _, _ = run_bot(diff, {"CLAUDE_CODE_OAUTH_TOKEN": SECRET})
        self.assertEqual(code, 0)
        self.assertIn("PR слишком большой для автоматического ревью (600 строк), review пропущен", body)

    def test_too_many_files_skips_model(self):
        diff = "".join(make_diff(f"app/f{i}.py", 1) for i in range(21))
        with mock.patch.object(review, "ask_model", side_effect=AssertionError):
            _, body, _, _ = run_bot(diff)
        self.assertIn("слишком большой", body)

    def test_threshold_is_configurable(self):
        diff = make_diff("app/a.py", 30)
        with mock.patch.object(review, "ask_model", side_effect=AssertionError):
            _, body, _, _ = run_bot(diff, {"MAX_DIFF_LINES": "10"})
        self.assertIn("слишком большой", body)

    def test_only_ignored_files(self):
        with mock.patch.object(review, "ask_model", side_effect=AssertionError):
            _, body, _, _ = run_bot(make_diff("yarn.lock", 900))
        self.assertIn("Нечего ревьюить", body)


class ParsingTest(unittest.TestCase):
    def test_plain_json(self):
        data = review.extract_json('{"comments": []}')
        self.assertEqual(data, {"comments": []})

    def test_json_in_code_fence_and_chatter(self):
        text = 'Вот ревью:\n```json\n{"comments": [{"file": "a.py", "severity": "error", "message": "m"}]}\n```\nГотово'
        comments, dropped = review.normalize_comments(review.extract_json(text))
        self.assertEqual((len(comments), dropped), (1, 0))

    def test_bad_entries_are_dropped_not_fatal(self):
        data = {"comments": [
            {"file": "a.py", "severity": "WARN", "message": "ok", "reason": "r"},
            {"file": "a.py", "severity": "catastrophic", "message": "bad severity"},
            {"file": "", "severity": "info", "message": "no file"},
            "строка вместо объекта",
        ]}
        comments, dropped = review.normalize_comments(data)
        self.assertEqual([c["severity"] for c in comments], ["warning"])
        self.assertEqual(dropped, 3)

    def test_garbage_is_none(self):
        self.assertIsNone(review.extract_json("Извините, я не могу помочь"))
        self.assertIsNone(review.normalize_comments({"foo": 1}))
        self.assertIsNone(review.normalize_comments({"comments": "нет"}))


class BotFlowTest(unittest.TestCase):
    ENV = {"CLAUDE_CODE_OAUTH_TOKEN": SECRET}

    def reply(self, text, meta=None):
        return mock.patch.object(review, "ask_model", return_value=(text, meta or {"model": "m", "tokens_in": 10, "tokens_out": 5}))

    def test_happy_path_renders_grouped_comments_and_json(self):
        answer = json.dumps({"comments": [
            {"file": "app/a.py", "severity": "info", "message": "стиль", "reason": "r"},
            {"file": "app/a.py", "severity": "error", "message": "SQL @admin", "reason": "почему"},
        ]})
        with self.reply(answer):
            code, body, _, saved = run_bot(make_diff("app/a.py", 5), self.ENV, json_out=True)
        self.assertEqual(code, 0)
        self.assertLess(body.index("error"), body.index("info"))
        self.assertIn("```json", body)
        self.assertNotIn("@admin", body)  # упоминания обезврежены
        self.assertEqual(len(saved["comments"]), 2)

    def test_empty_comments(self):
        with self.reply('{"comments": []}'):
            _, body, _, _ = run_bot(make_diff("app/a.py", 5), self.ENV)
        self.assertIn("Замечаний нет", body)

    def test_invalid_json_does_not_fail(self):
        with self.reply("это вообще не JSON ```"):
            code, body, _, _ = run_bot(make_diff("app/a.py", 5), self.ENV)
        self.assertEqual(code, 0)
        self.assertIn("не в формате JSON", body)

    def test_model_error_does_not_fail(self):
        with mock.patch.object(review, "ask_model", side_effect=review.LLMError("HTTP 429")):
            code, body, _, _ = run_bot(make_diff("app/a.py", 5), self.ENV)
        self.assertEqual(code, 0)
        self.assertIn("Ревью недоступно", body)

    def test_unexpected_crash_does_not_fail(self):
        with mock.patch.object(review, "build_prompt", side_effect=RuntimeError("boom")):
            code, body, _, _ = run_bot(make_diff("app/a.py", 5), self.ENV)
        self.assertEqual(code, 0)
        self.assertIn("Внутренняя ошибка бота", body)

    def test_missing_diff_file(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "review.md")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(review.main(["review.py", os.path.join(folder, "нет.txt"), out]), 0)
            self.assertTrue(os.path.exists(out))

    def test_no_key_message(self):
        code, body, _, _ = run_bot(make_diff("app/a.py", 5))
        self.assertEqual(code, 0)
        self.assertIn("не задан секрет CLAUDE_CODE_OAUTH_TOKEN", body)

    def test_instructions_are_in_the_prompt(self):
        captured = {}

        def fake(system, user):
            captured["system"], captured["user"] = system, user
            return '{"comments": []}', {"model": "m"}

        with mock.patch.object(review, "ask_model", side_effect=fake):
            run_bot(make_diff("app/a.py", 5), self.ENV)
        with open(os.path.join(HERE, "..", "review-instructions.md"), encoding="utf-8") as handle:
            instructions = handle.read()
        self.assertIn("S1. SQL собирается строкой", captured["user"])
        self.assertIn(instructions.strip()[:200], captured["user"])
        self.assertIn("+line 0", captured["user"])
        self.assertIn("ДАННЫЕ", captured["system"])

    def test_only_kept_files_reach_the_model(self):
        captured = {}

        def fake(system, user):
            captured["user"] = user
            return '{"comments": []}', {"model": "m"}

        diff = make_diff("app/a.py", 2) + make_diff("poetry.lock", 5) + make_diff("img.png", binary=True)
        with mock.patch.object(review, "ask_model", side_effect=fake):
            run_bot(diff, self.ENV)
        self.assertIn("app/a.py", captured["user"])
        self.assertNotIn("poetry.lock", captured["user"])
        self.assertNotIn("img.png", captured["user"])


class FakeServer:
    """Мини-сервер, имитирующий OpenAI-совместимый /chat/completions."""

    def __init__(self, script):
        self.script, self.calls, self.auth = list(script), 0, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                outer.calls += 1
                outer.auth.append(self.headers.get("Authorization"))
                status, payload = outer.script.pop(0) if outer.script else outer.last
                outer.last = (status, payload)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.last = (500, {})
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def completion(text):
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}


class OpenAIBackendTest(unittest.TestCase):
    def env(self, server):
        return {"LLM_BACKEND": "openai", "LLM_API_KEY": SECRET, "LLM_BASE_URL": server.url,
                "LLM_MODEL": "test-model", "LLM_RETRIES": "2"}

    def test_success_and_auth_header(self):
        server = FakeServer([(200, completion('{"comments": [{"file": "a.py", "severity": "error", "message": "m"}]}'))])
        self.addCleanup(server.close)
        code, body, _, _ = run_bot(make_diff("a.py", 3), self.env(server))
        self.assertEqual(code, 0)
        self.assertIn("🔴 error", body)
        self.assertEqual(server.auth, ["Bearer " + SECRET])
        self.assertNotIn(SECRET, body)

    def test_retries_on_429_then_succeeds(self):
        server = FakeServer([(429, {"error": "rate"}), (500, {"error": "oops"}), (200, completion('{"comments": []}'))])
        self.addCleanup(server.close)
        _, body, _, _ = run_bot(make_diff("a.py", 3), self.env(server))
        self.assertEqual(server.calls, 3)
        self.assertIn("Замечаний нет", body)

    def test_persistent_500_falls_back(self):
        server = FakeServer([(500, {"error": "down"})])
        self.addCleanup(server.close)
        code, body, err = run_bot(make_diff("a.py", 3), self.env(server))[:3]
        self.assertEqual(code, 0)
        self.assertEqual(server.calls, 3)
        self.assertIn("Ревью недоступно", body)
        self.assertNotIn(SECRET, body + err)

    def test_401_is_not_retried(self):
        server = FakeServer([(401, {"error": "bad key"})])
        self.addCleanup(server.close)
        _, body, _, _ = run_bot(make_diff("a.py", 3), self.env(server))
        self.assertEqual(server.calls, 1)
        self.assertIn("HTTP 401", body)

    def test_garbage_answer_falls_back(self):
        server = FakeServer([(200, completion("Не могу ответить JSON-ом"))])
        self.addCleanup(server.close)
        code, body, _, _ = run_bot(make_diff("a.py", 3), self.env(server))
        self.assertEqual(code, 0)
        self.assertIn("не в формате JSON", body)

    def test_non_json_http_body_falls_back(self):
        server = FakeServer([(200, b"<html>gateway</html>")])
        self.addCleanup(server.close)
        code, body, _, _ = run_bot(make_diff("a.py", 3), self.env(server))
        self.assertEqual(code, 0)
        self.assertIn("Ревью недоступно", body)

    def test_unreachable_server_falls_back(self):
        env = {"LLM_BACKEND": "openai", "LLM_API_KEY": SECRET, "LLM_BASE_URL": "http://127.0.0.1:9/v1",
               "LLM_RETRIES": "1", "LLM_TIMEOUT": "2"}
        code, body, _, _ = run_bot(make_diff("a.py", 3), env)
        self.assertEqual(code, 0)
        self.assertIn("Ревью недоступно", body)

    def test_missing_key(self):
        _, body, _, _ = run_bot(make_diff("a.py", 3), {"LLM_BACKEND": "openai"})
        self.assertIn("LLM_API_KEY", body)


STUB = """#!/usr/bin/env python3
import json, os, sys
config = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")))
mode = config["mode"]
stdin = sys.stdin.read()
record = {"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin_len": len(stdin),
          "env_keys": sorted(os.environ), "has_token": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))}
open(config["log"], "w").write(json.dumps(record))
if mode == "ok":
    answer = {"comments": [{"file": "a.py", "severity": "warning", "message": "stub", "reason": "r"}]}
    print(json.dumps({"type": "result", "is_error": False, "result": json.dumps(answer),
                      "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 5}}))
elif mode == "garbage":
    print(json.dumps({"type": "result", "is_error": False, "result": "не JSON"}))
elif mode == "auth":
    print(json.dumps({"type": "result", "is_error": True, "result": "Invalid API key · Please run /login"}))
    sys.exit(1)
elif mode == "crash":
    sys.stderr.write("segfault")
    sys.exit(2)
elif mode == "hang":
    import time; time.sleep(30)
"""


class ClaudeBackendTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        stub = os.path.join(self.folder, "claude")
        with open(stub, "w", encoding="utf-8") as handle:
            handle.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.folder, "log.json")
        self.env = {"PATH": self.folder + os.pathsep + os.environ.get("PATH", ""),
                    "CLAUDE_CODE_OAUTH_TOKEN": SECRET, "LLM_RETRIES": "1", "OTHER_SECRET": "must-not-leak"}

    def go(self, mode, **extra):
        """Задаёт поведение заглушки через файл рядом с ней (бот передаёт ей только нужные переменные)."""
        with open(os.path.join(self.folder, "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"mode": mode, "log": self.log}, handle)
        return run_bot(make_diff("a.py", 3), dict(self.env, **extra))

    def test_ok_flags_isolation_and_usage(self):
        code, body, _, _ = self.go("ok")
        self.assertEqual(code, 0)
        self.assertIn("stub", body)
        self.assertIn("токены: 105 вход / 20 выход", body)
        with open(self.log, encoding="utf-8") as handle:
            record = json.load(handle)
        argv = record["argv"]
        for flag in ("-p", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")  # все инструменты выключены
        self.assertIn("--system-prompt", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertTrue(record["has_token"])
        self.assertNotIn("OTHER_SECRET", record["env_keys"])  # лишние переменные не передаются
        self.assertNotEqual(os.path.realpath(record["cwd"]), os.path.realpath(os.getcwd()))  # не папка репозитория
        self.assertGreater(record["stdin_len"], 100)  # diff и чек-лист ушли через stdin
        self.assertNotIn(SECRET, body)

    def test_garbage_result(self):
        code, body, _, _ = self.go("garbage")
        self.assertEqual(code, 0)
        self.assertIn("не в формате JSON", body)

    def test_auth_error_not_retried_and_reported(self):
        code, body, err, _ = self.go("auth")
        self.assertEqual(code, 0)
        self.assertIn("Ревью недоступно", body)
        self.assertIn("login", body)
        self.assertEqual(err.count("попытка"), 1)

    def test_crash_is_retried_then_reported(self):
        code, body, err, _ = self.go("crash")
        self.assertEqual(code, 0)
        self.assertIn("Ревью недоступно", body)
        self.assertEqual(err.count("попытка"), 2)

    def test_timeout(self):
        code, body, _, _ = self.go("hang", LLM_TIMEOUT="1", LLM_RETRIES="1")
        self.assertEqual(code, 0)
        self.assertIn("не ответил", body)

    def test_claude_not_installed(self):
        code, body, _, _ = self.go("ok", PATH="/nonexistent")
        self.assertEqual(code, 0)
        self.assertIn("claude не найдена", body)


if __name__ == "__main__":
    unittest.main()
