#!/usr/bin/env python3
import json
import logging
import shutil
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path


class MailConfig(object):
    def __init__(self, smtp_host, smtp_port, smtp_username, smtp_password, use_tls,
                 from_email, to_email, cc_email, error_email, subject, body):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self.from_email = from_email
        self.to_email = to_email
        self.cc_email = cc_email
        self.error_email = error_email
        self.subject = subject
        self.body = body


class AppConfig(object):
    def __init__(self, source_dir, archive_dir, delete_sent_folders, log_file, mail):
        self.source_dir = source_dir
        self.archive_dir = archive_dir
        self.delete_sent_folders = delete_sent_folders
        self.log_file = log_file
        self.mail = mail


class ScanResult(object):
    def __init__(self, valid_dirs, invalid_dirs, orphan_files):
        self.valid_dirs = valid_dirs
        self.invalid_dirs = invalid_dirs
        self.orphan_files = orphan_files


REQUIRED_EXTENSIONS = {".dbf", ".xls"}


def load_config(config_path):
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


def _to_list(value):
    if isinstance(value, str):
        return [value]
    return list(value)


def setup_logging(log_file):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def scan_source_dir(source_dir):
    valid_dirs = []
    invalid_dirs = []
    orphan_files = []

    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError("Source directory not found: {}".format(source_dir))

    for child in sorted(source_dir.iterdir()):
        if child.is_dir():
            # Exception: folder "000Прочее_(000)" is always valid without validation
            if child.name == "000Прочее_(000)":
                valid_dirs.append(child)
                continue

            files = [file for file in child.iterdir() if file.is_file()]
            file_names = sorted(file.name for file in files)
            extensions = sorted(file.suffix.lower() for file in files)

            if len(files) != 2:
                invalid_dirs.append(
                    (
                        child,
                        "Найдено {} файла(ов), требуется ровно 2 файла (.dbf и .xls). Найденные файлы: {}".format(len(files), ', '.join(file_names) if file_names else 'нет файлов'),
                    )
                )
                continue

            if set(extensions) != REQUIRED_EXTENSIONS:
                invalid_dirs.append(
                    (
                        child,
                        "Требуются файлы .dbf и .xls. Найдены: {}".format(', '.join(file_names)),
                    )
                )
                continue

            if extensions.count('.dbf') != 1 or extensions.count('.xls') != 1:
                invalid_dirs.append(
                    (
                        child,
                        "Требуется ровно один файл .dbf и один файл .xls. Найдены: {}".format(', '.join(file_names)),
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
                        "Файл {} найден вне папки. Требуется разместить в подпапке с парным файлом".format(child.name),
                    )
                )

    return ScanResult(valid_dirs=valid_dirs, invalid_dirs=invalid_dirs, orphan_files=orphan_files)


def create_archive(source_dirs, archive_dir):
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    date_folder = archive_dir / timestamp
    date_folder.mkdir(parents=True, exist_ok=True)
    
    temp_root = date_folder / "subsidies_{}".format(datetime.now().strftime('%H%M%S'))
    temp_root.mkdir(parents=True, exist_ok=True)

    for source_dir in source_dirs:
        destination = temp_root / source_dir.name
        shutil.copytree(str(source_dir), str(destination))

    archive_path = shutil.make_archive(str(temp_root), "zip", root_dir=str(temp_root))
    shutil.rmtree(str(temp_root))
    return Path(archive_path)


def send_email_with_attachment(config, attachment_path):
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


def send_error_email(config, subject, body):
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


def delete_sent_dirs(source_dirs):
    failed = []
    for source_dir in source_dirs:
        try:
            shutil.rmtree(str(source_dir))
            logging.info("Deleted sent folder: %s", source_dir)
        except Exception as exc:  # noqa: BLE001
            failed.append((source_dir, str(exc)))
            logging.exception("Failed to delete folder after sending: %s", source_dir)
    return failed


def build_error_report(scan, delete_errors):
    lines = []

    if scan.invalid_dirs:
        lines.append("Невалидные папки:")
        for path, reason in scan.invalid_dirs:
            lines.append("- {}: {}".format(path, reason))

    if scan.orphan_files:
        if lines:
            lines.append("")
        lines.append("Файлы вне папок:")
        for path, reason in scan.orphan_files:
            lines.append("- {}: {}".format(path, reason))

    if delete_errors:
        if lines:
            lines.append("")
        lines.append("Папки, которые были отправлены, но не удалены:")
        for path, reason in delete_errors:
            lines.append("- {}: {}".format(path, reason))

    return "\n".join(lines) if lines else "Ошибок не detected."


def main():
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

        delete_errors = []
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
                body="Script failed with error:\n{}".format(exc),
            )
        except Exception:
            logging.exception("Failed to send fatal error email.")
        return 99


if __name__ == "__main__":
    raise SystemExit(main())
