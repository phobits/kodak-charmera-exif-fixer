from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

from ..core.models import ExifData


class ExiftoolPort(ABC):

    @abstractmethod
    def read_exif(self, file_path: Path) -> ExifData:
        ...

    @abstractmethod
    def write_exif(self, file_path: Path, values: Mapping[str, object]) -> None:
        """Write values keyed by ExifData field name (see EXIF_TAGS)."""
        ...
