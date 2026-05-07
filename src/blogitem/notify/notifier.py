"""Notifier — OS 데스크톱 알림 (plyer) + SMTP 백업.

P5 — 본격 구현.
"""

from __future__ import annotations


class Notifier:
    """알림 발송."""

    def desktop(self, *, title: str, message: str) -> None:
        """OS 네이티브 알림 (Windows toast / macOS Notification Center)."""
        raise NotImplementedError("P5 — plyer.notification 구현")

    def email(self, *, subject: str, body: str, to: str) -> None:
        """SMTP 이메일."""
        raise NotImplementedError("P5 — smtplib 구현")
