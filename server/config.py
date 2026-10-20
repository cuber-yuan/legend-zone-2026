import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secret_key: str
    secure_cookie: bool = False
    max_upload: int = 16 * 1024 * 1024
    step_timeout: float = 10
    human_timeout: float = 120
    auto_interval: float = 1800

    @property
    def database(self):
        return self.data_dir / "legend_zone.db"

    @property
    def uploads(self):
        return self.data_dir / "bots"

    @classmethod
    def load(cls):
        data = Path(os.environ.get("LEGEND_DATA_DIR", ROOT / "data")).resolve()
        secret = os.environ.get("LEGEND_SECRET_KEY")
        if not secret:
            path = data / "secret.key"
            if not path.is_file():
                raise RuntimeError(
                    "Run python -m server.cli init first, or set LEGEND_SECRET_KEY."
                )
            secret = path.read_text().strip()
        return cls(
            data,
            secret,
            os.environ.get("LEGEND_SECURE_COOKIE", "0") == "1",
            auto_interval=max(0, float(os.environ.get("LEGEND_AUTO_INTERVAL", "1800"))),
        )
