from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional


# Writable EXIF fields: ExifData attribute -> exiftool tag. ExifFix holds the same names
# with a "fixed_" prefix. A trailing "#" reads and writes the raw number instead of
# exiftool's formatted text (e.g. 35.0 instead of "35.0 mm").
EXIF_TAGS = {
    "modify_date": "ModifyDate",
    "datetime_original": "DateTimeOriginal",
    "create_date": "CreateDate",
    "exif_image_width": "ExifImageWidth",
    "exif_image_height": "ExifImageHeight",
    "make": "EXIF:Make",
    "model": "EXIF:Model",
    "lens_model": "EXIF:LensModel",
    "f_number": "EXIF:FNumber",
    "focal_length": "EXIF:FocalLength#",
    "focal_length_35mm": "EXIF:FocalLengthIn35mmFormat#",
    "user_comment": "EXIF:UserComment",
}


class FileType(Enum):
    PHOTO = "photo"
    VIDEO = "video"


class ProcessingStatus(Enum):
    PENDING = "pending"
    COPYING = "copying"
    FIXING_EXIF = "fixing_exif"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ExifData:
    modify_date: Optional[str] = None
    datetime_original: Optional[str] = None
    create_date: Optional[str] = None
    exif_image_width: Optional[int] = None
    exif_image_height: Optional[int] = None
    actual_image_width: Optional[int] = None
    actual_image_height: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    lens_model: Optional[str] = None
    f_number: Optional[float] = None
    focal_length: Optional[float] = None
    focal_length_35mm: Optional[int] = None
    user_comment: Optional[str] = None


@dataclass(frozen=True)
class ExifFix:
    fixed_modify_date: Optional[str] = None
    fixed_datetime_original: Optional[str] = None
    fixed_create_date: Optional[str] = None
    fixed_exif_image_width: Optional[int] = None
    fixed_exif_image_height: Optional[int] = None
    fixed_make: Optional[str] = None
    fixed_model: Optional[str] = None
    fixed_lens_model: Optional[str] = None
    fixed_f_number: Optional[float] = None
    fixed_focal_length: Optional[float] = None
    fixed_focal_length_35mm: Optional[int] = None
    fixed_user_comment: Optional[str] = None
    # Not a tag: marks dates above as taken from the file time rather than the camera.
    dates_from_file_time: bool = False

    def values(self) -> dict[str, object]:
        """Values to write, keyed like ExifData and EXIF_TAGS."""
        return {name: value for name in EXIF_TAGS
                if (value := getattr(self, f"fixed_{name}")) is not None}

    @property
    def has_fixes(self) -> bool:
        return bool(self.values())

    def labels(self) -> list[str]:
        """Short descriptions of the fixes, shared by all presenters."""
        names = self.values().keys()
        labels = []
        if names & {"lens_model", "f_number", "focal_length", "focal_length_35mm"}:
            labels.append("lens: manufacturer data")
        if names & {"make", "model"}:
            labels.append("camera: Kodak Charmera")
        if names & {"modify_date", "datetime_original", "create_date"}:
            labels.append("date from file time" if self.dates_from_file_time else "date")
        if names & {"exif_image_width", "exif_image_height"}:
            labels.append("dimensions")
        if not labels and "user_comment" in names:
            labels.append("provenance note")
        return labels


@dataclass
class CameraFile:
    source_path: Path
    file_type: FileType
    file_size: int
    file_modified: datetime
    exif_data: Optional[ExifData] = None
    exif_fix: Optional[ExifFix] = None
    destination_path: Optional[Path] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    error_message: Optional[str] = None


@dataclass(frozen=True)
class ProcessingPlan:
    files: list[CameraFile]
    destination_dir: Path
    total_copy_bytes: int

    @property
    def photo_count(self) -> int:
        return sum(1 for f in self.files if f.file_type == FileType.PHOTO)

    @property
    def video_count(self) -> int:
        return sum(1 for f in self.files if f.file_type == FileType.VIDEO)


@dataclass(frozen=True)
class ProgressEvent:
    file: CameraFile
    status: ProcessingStatus
    progress_percent: float
    message: str
    error: Optional[str] = None
    file_progress_percent: Optional[float] = None
    completed_files: int = 0
    total_files: int = 0
