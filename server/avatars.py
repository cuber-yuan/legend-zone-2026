"""Local avatar images, decoded and re-encoded independently of Bot uploads."""

import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 4 * 1024 * 1024


class Avatars:
    def __init__(self, data_dir):
        self.directory = Path(data_dir) / "avatars"

    def path(self, user_id):
        if type(user_id) is not int or user_id < 1:
            raise ValueError("Invalid user ID.")
        return self.directory / f"{user_id}.png"

    def url(self, user_id):
        return f"/api/avatars/{user_id}" if self.path(user_id).is_file() else None

    def save(self, user_id, raw):
        if not raw or len(raw) > MAX_AVATAR_BYTES:
            raise ValueError("Choose an image up to 4 MiB.")
        try:
            with Image.open(BytesIO(raw), formats=("JPEG", "PNG", "WEBP")) as image:
                if max(image.size) > 4096 or image.width * image.height > 16_000_000:
                    raise ValueError(
                        "Image dimensions must not exceed 4096 pixels or 16 megapixels."
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Choose a still image, not an animation.")
                image.load()
                cropped = ImageOps.fit(
                    ImageOps.exif_transpose(image).convert("RGBA"),
                    (256, 256),
                    method=Image.Resampling.LANCZOS,
                )
                # Copy only pixels so metadata, including EXIF location, is discarded.
                clean = Image.frombytes("RGBA", cropped.size, cropped.tobytes())
                output = BytesIO()
                clean.save(output, format="PNG")
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
        ) as error:
            raise ValueError("Choose a valid PNG, JPEG or WebP image.") from error
        target = self.path(user_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                dir=self.directory, suffix=".tmp", delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(output.getvalue())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remove(self, user_id):
        self.path(user_id).unlink(missing_ok=True)
