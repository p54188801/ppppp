"""核心工具单元测试（不依赖网络与数据库）。

覆盖：口令哈希、签名、校验器、时间工具、路由匹配。
运行：python -m unittest tests.test_core -v
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core import clock, ids, security, validators  # noqa: E402
from backend.core.errors import AppError, ValidationError  # noqa: E402
from backend.http.request import Request  # noqa: E402
from backend.http.router import Router  # noqa: E402
from backend.http.response import ok  # noqa: E402


class TestSecurity(unittest.TestCase):
    def test_hash_is_salted(self):
        h1, s1 = security.hash_password("Passw0rd!")
        h2, s2 = security.hash_password("Passw0rd!")
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(h1, h2)

    def test_verify_roundtrip(self):
        digest, salt = security.hash_password("机密口令abc")
        self.assertTrue(security.verify_password("机密口令abc", digest, salt))
        self.assertFalse(security.verify_password("机密口令abd", digest, salt))

    def test_hash_same_salt_stable(self):
        digest, salt = security.hash_password("abc123", "fixedsalt")
        again, _ = security.hash_password("abc123", salt)
        self.assertEqual(digest, again)

    def test_reject_short_password(self):
        with self.assertRaises(ValidationError):
            security.hash_password("123")

    def test_fullwidth_normalization(self):
        d1, s = security.hash_password("abc123")
        d2, _ = security.hash_password("ａｂｃ１２３", s)
        self.assertEqual(d1, d2)

    def test_sign_and_verify(self):
        payload = {"user": 1, "role": "admin"}
        token = security.sign_payload(payload)
        self.assertEqual(security.verify_signed(token), payload)
        self.assertIsNone(security.verify_signed(token + "x"))
        self.assertIsNone(security.verify_signed("garbage"))

    def test_token_entropy(self):
        token = security.new_session_token()
        self.assertEqual(len(token), 64)
        self.assertNotEqual(token, security.new_session_token())

    def test_password_strength(self):
        weak = security.password_strength("123456")
        strong = security.password_strength("Abc123!@#xyz")
        self.assertLess(weak["score"], strong["score"])


class TestIds(unittest.TestCase):
    def test_code_alphabet_excludes_confusing(self):
        for _ in range(50):
            code = ids.new_code(8)
            for ch in "01OIl":
                self.assertNotIn(ch, code)

    def test_attendance_code_is_digits(self):
        code = ids.new_attendance_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_mask_middle(self):
        self.assertEqual(ids.mask_middle("13800001234", 3), "138*****234".replace("*****", "*****"))
        self.assertTrue(ids.mask_middle("13800001234").startswith("138"))

    def test_clamp(self):
        self.assertEqual(ids.clamp(5, 1, 3), 3)
        self.assertEqual(ids.clamp(-1, 1, 3), 1)


class TestClock(unittest.TestCase):
    def test_iso_roundtrip(self):
        now = clock.utcnow()
        text = clock.to_iso(now)
        self.assertTrue(text.endswith("Z"))
        parsed = clock.parse_iso(text)
        self.assertIsNotNone(parsed)
        self.assertLess(abs((parsed - now).total_seconds()), 2)

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(clock.parse_iso("not-a-date"))
        self.assertIsNone(clock.parse_iso(""))
        self.assertIsNone(clock.parse_iso(None))

    def test_deadline_state(self):
        past = clock.to_iso(clock.utcnow() - timedelta(hours=1))
        future = clock.to_iso(clock.utcnow() + timedelta(days=3))
        soon = clock.to_iso(clock.utcnow() + timedelta(hours=1))
        self.assertEqual(clock.deadline_state(past), "overdue")
        self.assertEqual(clock.deadline_state(future), "open")
        self.assertEqual(clock.deadline_state(soon), "soon")
        self.assertEqual(clock.deadline_state(None), "none")

    def test_term_of(self):
        self.assertRegex(clock.term_of(), r"^\d{4}-\d{4}-[12]$")

    def test_humanize(self):
        self.assertEqual(clock.humanize_duration(30), "30 秒")
        self.assertIn("分钟", clock.humanize_duration(120))
        self.assertIn("小时", clock.humanize_duration(7200))


class TestValidators(unittest.TestCase):
    def test_required_str(self):
        self.assertEqual(validators.required_str({"a": " x "}, "a"), "x")
        with self.assertRaises(ValidationError):
            validators.required_str({}, "a")
        with self.assertRaises(ValidationError):
            validators.required_str({"a": "x" * 500}, "a", max_len=10)

    def test_to_int(self):
        self.assertEqual(validators.to_int("42", "n"), 42)
        with self.assertRaises(ValidationError):
            validators.to_int("4.2", "n")
        with self.assertRaises(ValidationError):
            validators.to_int(True, "n")
        with self.assertRaises(ValidationError):
            validators.to_int(5, "n", min_value=10)

    def test_to_float(self):
        self.assertEqual(validators.to_float("3.14159", "f"), 3.14)
        with self.assertRaises(ValidationError):
            validators.to_float("abc", "f")
        with self.assertRaises(ValidationError):
            validators.to_float(float("nan"), "f")

    def test_username(self):
        self.assertEqual(validators.validate_username("student_01"), "student_01")
        for bad in ("1abc", "ab", "a b", ""):
            with self.assertRaises(ValidationError):
                validators.validate_username(bad)

    def test_email_phone(self):
        self.assertEqual(validators.validate_email("a@b.com"), "a@b.com")
        with self.assertRaises(ValidationError):
            validators.validate_email("bad")
        self.assertEqual(validators.validate_phone("13800001234"), "13800001234")
        with self.assertRaises(ValidationError):
            validators.validate_phone("12345")

    def test_enum(self):
        self.assertEqual(validators.ensure_enum("a", ("a", "b"), "f"), "a")
        with self.assertRaises(ValidationError):
            validators.ensure_enum("c", ("a", "b"), "f")

    def test_bool(self):
        for raw in ("1", "true", "YES", 1, True):
            self.assertTrue(validators.to_bool(raw))
        for raw in ("0", "false", "no", 0, None):
            self.assertFalse(validators.to_bool(raw))

    def test_int_list(self):
        self.assertEqual(validators.parse_int_list("1,2,3"), [1, 2, 3])
        self.assertEqual(validators.parse_int_list([4, "5"]), [4, 5])

    def test_clamp_page(self):
        page, size = validators.clamp_page("0", "9999")
        self.assertEqual(page, 1)
        self.assertLessEqual(size, 200)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = Router()

        @self.router.get("/api/items/<int:item_id>", summary="取单个")
        def get_item(req):
            return ok({"id": req.path_params["item_id"]})

        @self.router.get("/api/items")
        def list_items(req):
            return ok([])

        @self.router.post("/api/items/<int:item_id>")
        def update_item(req):
            return ok({})

    def test_match_int_param(self):
        route, params = self.router.resolve("GET", "/api/items/42")
        self.assertEqual(params["item_id"], 42)
        self.assertEqual(route.summary, "取单个")

    def test_not_found(self):
        from backend.core.errors import NotFoundError

        with self.assertRaises(NotFoundError):
            self.router.resolve("GET", "/api/nope")

    def test_method_not_allowed(self):
        from backend.core.errors import MethodNotAllowedError

        with self.assertRaises(MethodNotAllowedError):
            self.router.resolve("DELETE", "/api/items/42")

    def test_describe(self):
        described = self.router.describe()
        self.assertEqual(len(described), 3)


class TestErrors(unittest.TestCase):
    def test_error_payload(self):
        from backend.core.errors import NotFoundError

        error = NotFoundError("没找到")
        payload = error.to_dict()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["message"], "没找到")
        self.assertEqual(error.status, 404)

    def test_inheritance(self):
        with self.assertRaises(AppError):
            raise ValidationError("x")


class TestRequest(unittest.TestCase):
    def test_json_body(self):
        req = Request(
            method="POST",
            raw_path="/api/x?a=1",
            headers={"content-type": "application/json"},
            body=b'{"name": "abc"}',
        )
        self.assertEqual(req.json()["name"], "abc")
        self.assertEqual(req.str_param("a"), "1")
        self.assertEqual(req.path, "/api/x")

    def test_bad_json(self):
        req = Request(method="POST", raw_path="/api/x", headers={}, body=b"{bad")
        with self.assertRaises(ValidationError):
            req.json()

    def test_bearer(self):
        req = Request(
            method="GET",
            raw_path="/",
            headers={"authorization": "Bearer abc123"},
            body=b"",
        )
        self.assertEqual(req.bearer_token, "abc123")

    def test_role_helpers(self):
        req = Request(method="GET", raw_path="/", headers={}, body=b"")
        req.user = {"id": 1, "role": "admin"}
        self.assertTrue(req.is_admin())
        self.assertTrue(req.is_teacher())
        self.assertFalse(req.has_role("student"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
