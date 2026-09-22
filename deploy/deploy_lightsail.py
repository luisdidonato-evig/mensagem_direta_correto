"""Deploy current workspace to the Evig Lightsail instance.

Run from repository root:
    uv run --with paramiko python deploy/deploy_lightsail.py

Requires an authenticated AWS CLI session. The temporary SSH private key stays
in memory and is discarded when the process exits.
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
import uuid
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization

INSTANCE_NAME = "evig-mensagem-direta-mvp"
REMOTE_ROOT = "/opt/evig"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def should_include(path: Path) -> bool:
    relative = path.relative_to(REPOSITORY_ROOT)
    parts = set(relative.parts)
    if parts & {".git", ".venv", "node_modules", "dist", "__pycache__"}:
        return False
    if parts & {".pytest_cache", ".ruff_cache"}:
        return False
    if path.name in {".env", ".env.production"}:
        return False
    if path.suffix in {".db", ".pyc"}:
        return False
    return True


def build_archive() -> io.BytesIO:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in REPOSITORY_ROOT.rglob("*"):
            if not path.is_file() or not should_include(path):
                continue
            archive.add(path, arcname=path.relative_to(REPOSITORY_ROOT).as_posix())
    buffer.seek(0)
    return buffer


def access_details() -> dict:
    output = subprocess.check_output(
        [
            "aws",
            "lightsail",
            "get-instance-access-details",
            "--instance-name",
            INSTANCE_NAME,
            "--protocol",
            "ssh",
            "--output",
            "json",
        ],
        text=True,
    )
    return json.loads(output)["accessDetails"]


def run(client: paramiko.SSHClient, command: str) -> None:
    print(f"> {command}", flush=True)
    _, stdout, stderr = client.exec_command(command, get_pty=True)
    for line in iter(stdout.readline, ""):
        print(line, end="", flush=True)
    error = stderr.read().decode(errors="replace")
    if error:
        print(error, end="", flush=True)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code:
        raise RuntimeError(f"Remote command failed with exit code {exit_code}")


def main() -> None:
    details = access_details()
    private_key = serialization.load_pem_private_key(
        details["privateKey"].encode(), password=None
    )
    traditional_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key = paramiko.ECDSAKey.from_private_key(io.StringIO(traditional_pem.decode()))
    key.load_certificate(details["certKey"])
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=details["ipAddress"],
        username=details["username"],
        pkey=key,
        timeout=20,
    )
    remote_archive = f"/tmp/evig-{uuid.uuid4().hex}.tar.gz"
    try:
        run(
            client,
            f"test -f {REMOTE_ROOT}/.env.production && "
            f"test -f {REMOTE_ROOT}/compose.production.yaml",
        )
        archive = build_archive()
        print(f"> uploading {archive.getbuffer().nbytes / 1024 / 1024:.1f} MiB", flush=True)
        with client.open_sftp() as sftp:
            with sftp.file(remote_archive, "wb") as remote_file:
                remote_file.write(archive.getvalue())
        run(
            client,
            f"sudo install -d -o $(id -u) -g $(id -g) {REMOTE_ROOT}/backups && "
            f"cd {REMOTE_ROOT} && "
            "docker compose --env-file .env.production -f compose.production.yaml "
            "exec -T postgres sh -c 'pg_dump -U evig evig_messages' | "
            f"gzip > {REMOTE_ROOT}/backups/predeploy-$(date +%Y%m%d-%H%M%S).sql.gz",
        )
        run(
            client,
            f"sudo tar --no-same-owner -xzf {remote_archive} -C {REMOTE_ROOT}",
        )
        compose = (
            f"cd {REMOTE_ROOT} && docker compose --env-file .env.production "
            "-f compose.production.yaml"
        )
        run(client, f"{compose} build backend worker beat frontend")
        run(client, f"{compose} run --rm backend alembic upgrade head")
        run(client, f"{compose} up -d --remove-orphans")
        run(client, f"{compose} ps")
        run(
            client,
            f"{compose} exec -T backend python -c \"import urllib.request; "
            "print(urllib.request.urlopen('http://localhost:8000/health').read().decode())\"",
        )
        run(client, f"{compose} exec -T backend alembic current")
    finally:
        try:
            run(client, f"rm -f {remote_archive}")
        finally:
            client.close()


if __name__ == "__main__":
    main()
