import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename


def root():
    return Path(current_app.config["STORAGE_DIR"])


def full(path):
    return root() / path


def clean_name(name):
    return secure_filename(Path(name or "").name) or "file"


def new_path(folder, name):
    path = Path(folder) / f"{uuid.uuid4().hex[:12]}_{clean_name(name)}"
    full(path).parent.mkdir(parents=True, exist_ok=True)
    return path.as_posix()


def save(file, folder):
    path = new_path(folder, file.filename)
    file.save(full(path))
    return path, full(path).stat().st_size


def write(data, folder, name):
    path = new_path(folder, name)
    full(path).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path, full(path).stat().st_size


def remove(path):
    try:
        full(path).unlink()
    except OSError:
        pass
