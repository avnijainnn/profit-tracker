#!/usr/bin/env python3
"""Stream pg_dump into age encryption. No plaintext dump or password on argv."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit, parse_qs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Private backup directory outside the repository")
    args = parser.parse_args()
    for command in ("pg_dump", "age"):
        if not shutil.which(command):
            parser.error(f"Install {command} before making a backup.")
    database_url = os.environ.get("DATABASE_URL", "")
    recipient = os.environ.get("BACKUP_AGE_RECIPIENT", "")
    parsed = urlsplit(database_url)
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname or not recipient.startswith("age1"):
        parser.error("Set a PostgreSQL DATABASE_URL and a public age BACKUP_AGE_RECIPIENT. Do not use a private key here.")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    repo = Path(__file__).resolve().parents[1]
    if args.output_dir.resolve().is_relative_to(repo):
        parser.error("Use a backup directory outside the source repository.")
    dump_env = dict(os.environ)
    dump_env.pop("DATABASE_URL", None)
    dump_env.update({"PGHOST": parsed.hostname, "PGPORT": str(parsed.port or 5432),
                     "PGUSER": unquote(parsed.username or ""), "PGPASSWORD": unquote(parsed.password or ""),
                     "PGDATABASE": unquote(parsed.path.lstrip("/")),
                     "PGSSLMODE": parse_qs(parsed.query).get("sslmode", ["require"])[0], "PGCONNECT_TIMEOUT": "15"})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = args.output_dir / f"profit-studio-{stamp}.dump.age"
    fd, temporary_name = tempfile.mkstemp(prefix=".pending-", suffix=".age", dir=args.output_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            dump = subprocess.Popen(["pg_dump", "--format=custom", "--no-owner", "--no-acl"], env=dump_env,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            encryption = subprocess.Popen(["age", "--recipient", recipient], stdin=dump.stdout,
                                          stdout=output, stderr=subprocess.DEVNULL)
            dump.stdout.close()
            encrypted_status = encryption.wait()
            dump_status = dump.wait()
            if encrypted_status or dump_status:
                raise RuntimeError("Backup failed. No complete backup was produced; check database connectivity, client version and encryption configuration.")
        temporary.replace(destination)
        print(f"Encrypted backup created: {destination}")
        print("Copy it to independent protected storage and verify restoration into a NEW isolated database.")
    finally:
        if temporary.exists():
            temporary.unlink()  # Only this script's private incomplete ciphertext file.


if __name__ == "__main__":
    main()
