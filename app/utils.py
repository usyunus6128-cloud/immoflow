import os
import shutil
from uuid import uuid4

UPLOAD_DIR = "uploads"


def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_upload_file(upload_file):
    ensure_upload_dir()

    unique_name = f"{uuid4()}_{upload_file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    return unique_name, file_path