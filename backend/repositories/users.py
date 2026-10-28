"""用户、会话、登录记录的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    table = "users"
    writable = (
        "username",
        "password_hash",
        "password_salt",
        "role",
        "real_name",
        "number",
        "email",
        "phone",
        "department",
        "class_name",
        "avatar",
        "status",
        "must_change_password",
        "last_login_at",
    )

    def by_username(self, username: str) -> dict[str, Any] | None:
        """用户名不区分大小写（PPPPP 和 ppppp 视为同一个）。"""
        return connection.query_one(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
            (username,),
        )

    def by_number(self, number: str) -> dict[str, Any] | None:
        return connection.query_one(
            "SELECT * FROM users WHERE number = ? COLLATE NOCASE LIMIT 1", (number,)
        )

    def list_by_role(self, role: str, *, keyword: str = "",
                     limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT * FROM users WHERE role = ?"
        params: list[Any] = [role]
        if keyword:
            sql += " AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return connection.query_all(sql, tuple(params))

    def count_by_role(self, role: str, keyword: str = "") -> int:
        sql = "SELECT COUNT(*) FROM users WHERE role = ?"
        params: list[Any] = [role]
        if keyword:
            sql += " AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        return int(connection.scalar(sql, tuple(params), default=0) or 0)

    def search(self, keyword: str, *, limit: int = 20) -> list[dict[str, Any]]:
        like = f"%{keyword}%"
        return connection.query_all(
            """SELECT id, username, real_name, role, number, department
               FROM users
               WHERE status = 'active'
                 AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)
               ORDER BY role, id
               LIMIT ?""",
            (like, like, like, limit),
        )

    def touch_login(self, user_id: int) -> None:
        connection.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (clock.now_iso(), clock.now_iso(), user_id),
        )

    def set_password(self, user_id: int, password_hash: str, salt: str,
                     must_change: bool = False) -> None:
        connection.execute(
            """UPDATE users
                  SET password_hash = ?, password_salt = ?, must_change_password = ?,
                      updated_at = ?
                WHERE id = ?""",
            (password_hash, salt, 1 if must_change else 0, clock.now_iso(), user_id),
        )

    def set_status(self, user_id: int, status: str) -> None:
        connection.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
            (status, clock.now_iso(), user_id),
        )

    def count_all(self) -> dict[str, int]:
        rows = connection.query_all(
            "SELECT role, COUNT(*) AS n FROM users GROUP BY role"
        )
        result = {"student": 0, "teacher": 0, "admin": 0}
        for row in rows:
            result[row["role"]] = row["n"]
        return result

    def departments(self) -> list[str]:
        rows = connection.query_all(
            """SELECT DISTINCT department FROM users
               WHERE department IS NOT NULL AND department <> ''
               ORDER BY department"""
        )
        return [row["department"] for row in rows]


class SessionRepository(BaseRepository):
    table = "sessions"
    writable = ("user_id", "token", "user_agent", "ip", "expires_at", "revoked_at")
    created_field = "created_at"
    updated_field = ""

    def by_token(self, token: str) -> dict[str, Any] | None:
        return self.find_by(token=token)

    def create(self, user_id: int, token: str, expires_at: str,
               *, ip: str = "", user_agent: str = "") -> int:
        return self.insert(
            {
                "user_id": user_id,
                "token": token,
                "expires_at": expires_at,
                "ip": ip,
                "user_agent": user_agent[:300],
            }
        )

    def revoke(self, token: str) -> None:
        connection.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token = ?",
            (clock.now_iso(), token),
        )

    def revoke_all_for_user(self, user_id: int) -> int:
        return connection.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (clock.now_iso(), user_id),
        )

    def purge_expired(self) -> int:
        return connection.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (clock.now_iso(),)
        )

    def active_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT id, ip, user_agent, created_at, expires_at
                 FROM sessions
                WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC""",
            (user_id, clock.now_iso()),
        )


class LoginAttemptRepository(BaseRepository):
    table = "login_attempts"
    writable = ("username", "success", "ip")
    created_field = "created_at"
    updated_field = ""

    def record(self, username: str, success: bool, ip: str = "") -> None:
        self.insert({"username": username, "success": 1 if success else 0, "ip": ip})

    def recent_failures(self, username: str, seconds: int) -> int:
        threshold = clock.from_timestamp(
            clock.utcnow().timestamp() - seconds
        )
        return int(
            connection.scalar(
                """SELECT COUNT(*) FROM login_attempts
                    WHERE username = ? AND success = 0 AND created_at > ?""",
                (username, threshold),
                default=0,
            )
            or 0
        )

    def last_failure_at(self, username: str) -> str | None:
        return connection.scalar(
            """SELECT created_at FROM login_attempts
                WHERE username = ? AND success = 0
                ORDER BY id DESC LIMIT 1""",
            (username,),
        )

    def clear(self, username: str) -> None:
        connection.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
