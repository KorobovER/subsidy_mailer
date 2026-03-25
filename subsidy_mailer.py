#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import shutil
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import List, Tuple


@dataclass
class MailConfig:
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    use_tls: bool
    from_email: str
    to_email: List[str]
    cc_email: List[str]
    error_email: List[str]
    subject: str
    body: str


@dataclass
class AppConfig:
    source_dir: Path
    archive_dir: Path
    delete_sent_folders: bool
    log_file: Path
    mail: MailConfig


@dataclass
class ScanResult:
    valid_dirs: List[Path]
    invalid_dirs: List[Tuple[Path, str]]
    orphan_files: List[Tuple[Path, str]]


REQUIRED_EXTENSIONS = {".dbf", ".xls"}


def load_config(config_path: Path) -> AppConfig:
    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    # Mail config is optional for testing
    if "mail" in raw:
        mail_raw = raw["mail"]
        mail = MailConfig(
            smtp_host=mail_raw["smtp_host"],
            smtp_port=int(mail_raw.get("smtp_port", 587)),
            smtp_username=mail_raw["smtp_username"],
            smtp_password=mail_raw["smtp_password"],
            use_tls=bool(mail_raw.get("use_tls", True)),
            from_email=mail_raw["from_email"],
            to_email=_to_list(mail_raw["to_email"]),
            cc_email=_to_list(mail_raw.get("cc_email", [])),
            error_email=_to_list(mail_raw.get("error_email", [])),
            subject=mail_raw["subject"],
            body=mail_raw["body"],
        )
    else:
        # Dummy mail config for testing
        mail = MailConfig(
            smtp_host="", smtp_port=587, smtp_username="", smtp_password="",
            use_tls=True, from_email="", to_email=[], cc_email=[], error_email=[],
            subject="", body=""
        )

    return AppConfig(
        source_dir=Path(raw["source_dir"]),
        archive_dir=Path(raw.get("archive_dir", "./archives")),
        delete_sent_folders=bool(raw.get("delete_sent_folders", True)),
        log_file=Path(raw.get("log_file", "./subsidy_mailer.log")),
        mail=mail,
    )


def _to_list(value: str | List[str]) -> List[str]:
    if isinstance(value, str):
        return [value]
    return list(value)


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def scan_source_dir(source_dir: Path) -> ScanResult:
    valid_dirs: List[Path] = []
    invalid_dirs: List[Tuple[Path, str]] = []
    orphan_files: List[Tuple[Path, str]] = []

    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    for child in sorted(source_dir.iterdir()):
        if child.is_dir():
            files = [file for file in child.iterdir() if file.is_file()]
            file_names = sorted(file.name for file in files)
            extensions = sorted(file.suffix.lower() for file in files)

            if len(files) != 2:
                invalid_dirs.append(
                    (
                        child,
                        f"Найдено {len(files)} файла(ов), требуется ровно 2 файла (.dbf и .xls). Найденные файлы: {', '.join(file_names) if file_names else 'нет файлов'}",
                    )
                )
                continue

            if set(extensions) != REQUIRED_EXTENSIONS:
                invalid_dirs.append(
                    (
                        child,
                        f"Требуются файлы .dbf и .xls. Найдены: {', '.join(file_names)}",
                    )
                )
                continue

            if extensions.count('.dbf') != 1 or extensions.count('.xls') != 1:
                invalid_dirs.append(
                    (
                        child,
                        f"Требуется ровно один файл .dbf и один файл .xls. Найдены: {', '.join(file_names)}",
                    )
                )
                continue

            valid_dirs.append(child)
        elif child.is_file():
            # Файлы вне папок
            if child.suffix.lower() in REQUIRED_EXTENSIONS:
                orphan_files.append(
                    (
                        child,
                        f"Файл {child.name} найден вне папки. Требуется разместить в подпапке с парным файлом",
                    )
                )

    return ScanResult(valid_dirs=valid_dirs, invalid_dirs=invalid_dirs, orphan_files=orphan_files)


def create_archive(source_dirs: List[Path], archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_root = archive_dir / f"subsidies_{timestamp}"
    temp_root.mkdir(parents=True, exist_ok=True)

    for source_dir in source_dirs:
        destination = temp_root / source_dir.name
        shutil.copytree(source_dir, destination)

    archive_path = shutil.make_archive(str(temp_root), "zip", root_dir=temp_root)
    shutil.rmtree(temp_root)
    return Path(archive_path)


def send_email_with_attachment(config: AppConfig, attachment_path: Path) -> None:
    msg = EmailMessage()
    msg["Subject"] = config.mail.subject
    msg["From"] = config.mail.from_email
    msg["To"] = ", ".join(config.mail.to_email)
    if config.mail.cc_email:
        msg["Cc"] = ", ".join(config.mail.cc_email)
    msg.set_content(config.mail.body)

    with attachment_path.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="zip",
            filename=attachment_path.name,
        )

    recipients = config.mail.to_email + config.mail.cc_email

    with smtplib.SMTP(config.mail.smtp_host, config.mail.smtp_port, timeout=60) as smtp:
        if config.mail.use_tls:
            smtp.starttls()
        if config.mail.smtp_username:
            smtp.login(config.mail.smtp_username, config.mail.smtp_password)
        smtp.send_message(msg, to_addrs=recipients)


def send_error_email(config: AppConfig, subject: str, body: str) -> None:
    if not config.mail.error_email:
        logging.warning("Error email recipients are not configured. Error email skipped.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.mail.from_email
    msg["To"] = ", ".join(config.mail.error_email)
    msg.set_content(body)

    with smtplib.SMTP(config.mail.smtp_host, config.mail.smtp_port, timeout=60) as smtp:
        if config.mail.use_tls:
            smtp.starttls()
        if config.mail.smtp_username:
            smtp.login(config.mail.smtp_username, config.mail.smtp_password)
        smtp.send_message(msg, to_addrs=config.mail.error_email)


def delete_sent_dirs(source_dirs: List[Path]) -> List[Tuple[Path, str]]:
    failed: List[Tuple[Path, str]] = []
    for source_dir in source_dirs:
        try:
            shutil.rmtree(source_dir)
            logging.info("Deleted sent folder: %s", source_dir)
        except Exception as exc:  # noqa: BLE001
            failed.append((source_dir, str(exc)))
            logging.exception("Failed to delete folder after sending: %s", source_dir)
    return failed


def build_error_report(scan: ScanResult, delete_errors: List[Tuple[Path, str]]) -> str:
    lines = []

    if scan.invalid_dirs:
        lines.append("Невалидные папки:")
        for path, reason in scan.invalid_dirs:
            lines.append(f"- {path}: {reason}")

    if scan.orphan_files:
        if lines:
            lines.append("")
        lines.append("Файлы вне папок:")
        for path, reason in scan.orphan_files:
            lines.append(f"- {path}: {reason}")

    if delete_errors:
        if lines:
            lines.append("")
        lines.append("Папки, которые были отправлены, но не удалены:")
        for path, reason in delete_errors:
            lines.append(f"- {path}: {reason}")

    return "\n".join(lines) if lines else "Ошибок не detected."


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    config = load_config(config_path)
    setup_logging(config.log_file)

    logging.info("Started processing. Source dir: %s", config.source_dir)

    try:
        scan = scan_source_dir(config.source_dir)
        logging.info("Valid folders found: %s", len(scan.valid_dirs))
        logging.info("Invalid folders found: %s", len(scan.invalid_dirs))
        logging.info("Orphan files found: %s", len(scan.orphan_files))

        if not scan.valid_dirs:
            message = "Нет валидных папок для отправки."
            if scan.invalid_dirs or scan.orphan_files:
                message += " Найдены ошибки; подробности в логе."
            logging.warning(message)

            if scan.invalid_dirs or scan.orphan_files:
                report = build_error_report(scan, [])
                send_error_email(
                    config,
                    subject="Ошибка выгрузки субсидий: нет валидных папок",
                    body=report,
                )
            return 1

        archive_path = create_archive(scan.valid_dirs, config.archive_dir)
        logging.info("Archive created: %s", archive_path)

        send_email_with_attachment(config, archive_path)
        logging.info("Archive sent successfully to: %s", ", ".join(config.mail.to_email))

        delete_errors: List[Tuple[Path, str]] = []
        if config.delete_sent_folders:
            delete_errors = delete_sent_dirs(scan.valid_dirs)

        if scan.invalid_dirs or scan.orphan_files or delete_errors:
            report = build_error_report(scan, delete_errors)
            logging.error("Processing completed with errors:\n%s", report)
            send_error_email(
                config,
                subject="Ошибка выгрузки субсидий",
                body=report,
            )
            return 2

        logging.info("Processing completed successfully.")
        return 0

    except Exception as exc:  # noqa: BLE001
        logging.exception("Fatal error: %s", exc)
        try:
            send_error_email(
                config,
                subject="Критическая ошибка выгрузки субсидий",
                body=f"Script failed with error:\n{exc}",
            )
        except Exception:
            logging.exception("Failed to send fatal error email.")
        return 99


if __name__ == "__main__":
    raise SystemExit(main())
