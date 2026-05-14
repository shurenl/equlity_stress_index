from __future__ import annotations

from pathlib import Path

import pytest

from src.email_report import build_message, latest_report_path


def test_latest_report_path_picks_latest_by_name(tmp_path):
    first = tmp_path / "esi_daily_report_2026-05-12.pdf"
    second = tmp_path / "esi_daily_report_2026-05-13.pdf"
    first.write_bytes(b"%PDF first")
    second.write_bytes(b"%PDF second")

    assert latest_report_path(tmp_path) == second


def test_latest_report_path_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        latest_report_path(tmp_path)


def test_build_message_attaches_pdf(tmp_path):
    report = tmp_path / "esi_daily_report_2026-05-13.pdf"
    report.write_bytes(b"%PDF sample content")

    message = build_message(
        sender="sender@gmail.com",
        recipient="recipient@gmail.com",
        report_path=report,
    )

    assert message["From"] == "sender@gmail.com"
    assert message["To"] == "recipient@gmail.com"
    assert "2026-05-13" in message["Subject"]

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == report.name
    assert attachments[0].get_content_type() == "application/pdf"


def test_build_message_requires_existing_pdf(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_message(
            sender="sender@gmail.com",
            recipient="recipient@gmail.com",
            report_path=Path(tmp_path / "missing.pdf"),
        )

