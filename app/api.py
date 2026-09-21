from __future__ import annotations

import os
from pathlib import Path
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from app.config import Settings


UPLOAD_CHUNK_SIZE = 1024 * 1024


def _safe_filename(filename: str | None) -> str:
    return Path(filename or "").name or "upload"


async def persist_upload(upload: UploadFile, incoming_dir: Path, submission_id: uuid.UUID) -> Path:
    safe_filename = _safe_filename(upload.filename)
    temporary_path = incoming_dir / f".upload-{submission_id}.tmp"
    final_path = incoming_dir / f"{submission_id}-{safe_filename}"

    incoming_dir.mkdir(parents=True, exist_ok=True)
    try:
        with temporary_path.open("xb") as destination:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, final_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        try:
            await upload.close()
        except Exception:
            pass

    return final_path


def create_app(settings: Settings | None = None) -> FastAPI:
    configured_settings = settings or Settings.from_environment()
    app = FastAPI(title="AI Invoice Auditor Upload API")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post("/api/v1/invoices", status_code=status.HTTP_202_ACCEPTED)
    async def submit_invoice(file: UploadFile = File(...)) -> dict[str, str]:
        submission_id = uuid.uuid4()
        safe_filename = _safe_filename(file.filename)
        try:
            await persist_upload(file, configured_settings.incoming_dir, submission_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Upload could not be completed",
            ) from exc
        return {
            "submission_id": str(submission_id),
            "filename": safe_filename,
            "status": "SUBMITTED",
        }

    return app


app = create_app()
