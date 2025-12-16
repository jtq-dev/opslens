import os
from pydantic import BaseModel

class Settings(BaseModel):
    db_path: str = os.environ.get("OPSLENS_DB_PATH", "opslens.db")
    max_upload_mb: int = int(os.environ.get("OPSLENS_MAX_UPLOAD_MB", "20"))

settings = Settings()
