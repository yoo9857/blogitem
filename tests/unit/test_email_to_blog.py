"""EmailToBlogChannel — SMTP 메일 발행 폴백."""

from __future__ import annotations

import smtplib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blogitem.channels.base import PublishError
from blogitem.channels.email_to_blog import EmailToBlogChannel


def _make_channel(*, dry_run: bool = False, port: int = 587) -> EmailToBlogChannel:
    return EmailToBlogChannel(
        smtp_host="smtp.example.com",
        smtp_port=port,
        smtp_user="user@example.com",
        smtp_password="secret",
        smtp_from="user@example.com",
        publish_email="blog@naver.com",
        dry_run=dry_run,
    )


class TestConstructor:
    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            EmailToBlogChannel(
                smtp_host="",
                smtp_port=587,
                smtp_user="u",
                smtp_password="p",
                smtp_from="f",
                publish_email="t",
            )

    def test_invalid_port_rejected(self) -> None:
        with pytest.raises(ValueError):
            _make_channel(port=70000)


class TestPublishDryRun:
    def test_skips_smtp_call(self) -> None:
        ch = _make_channel(dry_run=True)
        with patch("smtplib.SMTP") as smtp_mock, patch("smtplib.SMTP_SSL") as ssl_mock:
            result = ch.publish(
                title="t",
                contents_html="<p>x</p>",
                image_paths=[],
            )
        smtp_mock.assert_not_called()
        ssl_mock.assert_not_called()
        assert result.channel == "email_to_blog"
        assert result.external_id.startswith("<")
        assert result.external_id.endswith("@blogitem>")


class TestPublishLive:
    def test_smtp_starttls_flow(self) -> None:
        ch = _make_channel(port=587)
        smtp_instance = MagicMock()
        smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
        smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
            result = ch.publish(
                title="제목",
                contents_html="<h1>본문</h1>",
                image_paths=[],
                tags=["a", "b"],
            )

        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once_with("user@example.com", "secret")
        smtp_instance.send_message.assert_called_once()
        assert result.channel == "email_to_blog"
        assert result.external_id.startswith("<")

    def test_smtp_ssl_flow_for_port_465(self) -> None:
        ch = _make_channel(port=465)
        ssl_instance = MagicMock()
        ssl_instance.__enter__ = MagicMock(return_value=ssl_instance)
        ssl_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP_SSL", return_value=ssl_instance) as ssl_cls:
            ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

        ssl_cls.assert_called_once()
        ssl_instance.login.assert_called_once()
        ssl_instance.send_message.assert_called_once()

    def test_smtp_failure_raises_publish_error(self) -> None:
        ch = _make_channel()

        smtp_instance = MagicMock()
        smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
        smtp_instance.__exit__ = MagicMock(return_value=False)
        smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"auth failed"
        )

        with patch("smtplib.SMTP", return_value=smtp_instance):
            with pytest.raises(PublishError) as exc:
                ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

        assert exc.value.channel == "email_to_blog"
        # AuthenticationError 는 영구 실패
        assert exc.value.retryable is False

    def test_disconnect_marked_retryable(self) -> None:
        ch = _make_channel()
        smtp_instance = MagicMock()
        smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
        smtp_instance.__exit__ = MagicMock(return_value=False)
        smtp_instance.send_message.side_effect = smtplib.SMTPServerDisconnected("gone")

        with patch("smtplib.SMTP", return_value=smtp_instance):
            with pytest.raises(PublishError) as exc:
                ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

        assert exc.value.retryable is True


class TestValidation:
    def test_empty_title_rejected(self) -> None:
        ch = _make_channel(dry_run=True)
        with pytest.raises(ValueError):
            ch.publish(title="", contents_html="<p>x</p>", image_paths=[])

    def test_empty_contents_rejected(self) -> None:
        ch = _make_channel(dry_run=True)
        with pytest.raises(ValueError):
            ch.publish(title="t", contents_html="", image_paths=[])
