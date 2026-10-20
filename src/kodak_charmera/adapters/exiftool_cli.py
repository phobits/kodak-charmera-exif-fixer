import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ..core.models import EXIF_TAGS, ExifData
from ..ports.exiftool_port import ExiftoolPort


class ExiftoolCliAdapter(ExiftoolPort):

    def __init__(self, exiftool_path: str = "exiftool"):
        self._exe = exiftool_path

    def read_exif(self, file_path: Path) -> ExifData:
        result = subprocess.run(
            [self._exe, "-json", "-ImageWidth", "-ImageHeight",
             *(f"-{tag}" for tag in EXIF_TAGS.values()), str(file_path)],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)[0]
        return ExifData(
            actual_image_width=data.get("ImageWidth"),
            actual_image_height=data.get("ImageHeight"),
            **{name: data.get(tag.split(":")[-1].rstrip("#"))
               for name, tag in EXIF_TAGS.items()},
        )

    def rebuild_exif(self, file_path: Path) -> None:
        """Rebuild EXIF structure to fix corrupt MakerNote/IFD entries."""
        subprocess.run(
            [
                self._exe,
                "-all=", "-tagsfromfile", "@",
                "-all:all", "-unsafe",
                "-overwrite_original",
                str(file_path),
            ],
            capture_output=True, text=True, check=True,
        )

    def write_exif(self, file_path: Path, values: Mapping[str, object]) -> None:
        # Rebuild EXIF first to fix corrupt structure from Charmera
        self.rebuild_exif(file_path)

        args = [self._exe, "-overwrite_original"]
        args += [f"-{EXIF_TAGS[name]}={value}" for name, value in values.items()]
        args.append(str(file_path))
        subprocess.run(args, capture_output=True, text=True, check=True)
