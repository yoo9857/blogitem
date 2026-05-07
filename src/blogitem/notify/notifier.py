"""Notifier — OS 데스크톱 알림 (plyer) + 로그 fallback.

플랫폼별 백엔드:
    · Windows: toast (Action Center)
    · macOS:  Notification Center
    · Linux:  libnotify
"""

from __future__ import annotations


class Notifier:
    """알림 발송.

    plyer 가 일부 환경(헤드리스/CI)에서 fail 할 수 있으므로 BLE 로 보호하고
    로그에 기록. 알림 실패가 호출 흐름을 깨면 안 됨.
    """

    APP_NAME = "blogitem"

    def desktop(self, *, title: str, message: str, timeout: int = 10) -> bool:
        """OS 네이티브 알림. 성공 시 True, 실패 시 False (로그 기록)."""
        from blogitem.log import get_logger

        log = get_logger(__name__)
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name=self.APP_NAME,
                timeout=timeout,
            )
            log.info("notify.desktop_ok", title=title)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning(
                "notify.desktop_failed",
                title=title,
                err=f"{type(e).__name__}: {e}",
            )
            return False
