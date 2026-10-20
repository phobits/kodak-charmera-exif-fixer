from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import CameraFile, ExifData, ExifFix, FileType
from ..ports.exiftool_port import ExiftoolPort
from ..ports.filesystem_port import FilesystemPort


PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg"})
VIDEO_EXTENSIONS = frozenset({".avi"})
_NOTE_PREFIX = "Charmera EXIF Fixer: "
_NOTE_CLAUSES = {
    "lens": "LensModel is a descriptive label",
    "aperture": "FNumber=2.4 is the nominal manufacturer aperture, not measured exposure",
    "focal": ("FocalLength/FocalLengthIn35mmFormat=35 is the advertised 35mm-equivalent, "
              "written to FocalLength for display, although the actual focal length of the "
              "1/4-inch sensor lens is shorter"),
    "dates": ("the camera wrote no capture date, so missing dates were taken from the file "
              "modification time"),
}
# Clause openings written by this and earlier versions of the note.
_NOTE_MARKERS = {
    "lens": ("LensModel is",),
    "aperture": ("FNumber=2.4",),
    "focal": ("FocalLength/", "FocalLengthIn35mmFormat=35"),
    "dates": ("the camera wrote no capture date", "missing capture dates"),
}


class CameraScanner:

    def __init__(self, filesystem: FilesystemPort, exiftool: ExiftoolPort):
        self._fs = filesystem
        self._exiftool = exiftool

    def scan(self, volume_path: Path) -> list[CameraFile]:
        dcim = next((p for p in sorted(volume_path.iterdir())
                     if p.name.casefold() == "dcim" and p.is_dir()), volume_path)
        files: list[CameraFile] = []

        for path in sorted(self._fs.list_files(dcim, recursive=True)):
            # Skip macOS metadata files
            if path.name.startswith("._") or path.is_symlink():
                continue

            file_type = self._classify_file(path)
            if file_type is None:
                continue

            camera_file = CameraFile(
                source_path=path,
                file_type=file_type,
                file_size=self._fs.file_size(path),
                file_modified=self._fs.file_mtime(path),
            )

            if file_type == FileType.PHOTO:
                exif = self._exiftool.read_exif(path)
                camera_file.exif_data = exif
                camera_file.exif_fix = self._compute_exif_fix(exif, camera_file.file_modified)

            files.append(camera_file)

        return files

    def _classify_file(self, path: Path) -> Optional[FileType]:
        ext = path.suffix.lower()
        if ext in PHOTO_EXTENSIONS:
            return FileType.PHOTO
        if ext in VIDEO_EXTENSIONS:
            return FileType.VIDEO
        return None

    def _compute_exif_fix(
        self, exif: ExifData, file_modified: Optional[datetime] = None,
    ) -> ExifFix:
        raw_dates = (exif.modify_date, exif.datetime_original, exif.create_date)
        valid_dates = [self._normalize_date(raw) for raw in raw_dates]
        # A missing date reuses the capture date of the same photo. ModifyDate may be a
        # later edit time, so it never stands in for one; without a capture date the file
        # time is the only source left (the camera often writes no EXIF at all).
        capture_date = valid_dates[1] or valid_dates[2]
        file_time = self._format_date(file_modified) if file_modified else None
        fallback = capture_date or file_time
        dates = [None if valid is not None and valid == raw else valid or fallback
                 for raw, valid in zip(raw_dates, valid_dates)]
        dates_from_file_time = capture_date is None and file_time is not None
        lens_model = "Kodak Charmera built-in lens" if not exif.lens_model else None
        f_number = 2.4 if exif.f_number is None else None
        # EXIF defines a focal length of 0 as unknown. A tag is only filled where it cannot
        # contradict the other one, which may already hold the same advertised 35.
        focal = 35.0 if not exif.focal_length and (exif.focal_length_35mm or 35) == 35 else None
        focal_35mm = 35 if not exif.focal_length_35mm and (exif.focal_length or 35) == 35 else None
        topics = {topic for topic, added in (
            ("lens", lens_model), ("aperture", f_number), ("focal", focal or focal_35mm),
            ("dates", dates_from_file_time)) if added}
        comment = self._merge_note(exif.user_comment, topics) if topics else None
        return ExifFix(
            fixed_lens_model=lens_model,
            fixed_f_number=f_number,
            fixed_focal_length=focal,
            fixed_focal_length_35mm=focal_35mm,
            fixed_user_comment=comment,
            fixed_modify_date=dates[0],
            fixed_datetime_original=dates[1],
            fixed_create_date=dates[2],
            dates_from_file_time=dates_from_file_time,
            fixed_exif_image_width=self._fix_dimension(exif.exif_image_width, exif.actual_image_width),
            fixed_exif_image_height=self._fix_dimension(exif.exif_image_height, exif.actual_image_height),
            fixed_make="Kodak" if exif.make != "Kodak" else None,
            fixed_model="Charmera" if exif.model != "Charmera" else None,
        )

    @staticmethod
    def _merge_note(user_comment: Optional[str], topics: set[str]) -> str:
        """Append a fresh fixer note to the user's comment, replacing earlier fixer notes.

        Fixer notes always occupy whole lines, so the user's text is kept as written.
        Topics noted by an earlier run are carried over, since those values stay in place.
        """
        lines = (user_comment or "").split("\n")
        user_text = "\n".join(line for line in lines if not line.startswith(_NOTE_PREFIX))
        old_notes = " ".join(line for line in lines if line.startswith(_NOTE_PREFIX))
        topics = topics | {topic for topic, markers in _NOTE_MARKERS.items()
                           if any(marker in old_notes for marker in markers)}
        note = _NOTE_PREFIX + "; ".join(
            clause for topic, clause in _NOTE_CLAUSES.items() if topic in topics) + "."
        if topics & {"lens", "aperture", "focal"}:
            note += (" Manufacturer lists lens as 35mm F2.4. Source: "
                     "https://www.kodak.retopro.co/products/"
                     "kodak-charmera-br-keychain-digital-camera-blind-box")
        return (user_text + "\n" if user_text else "") + note

    @staticmethod
    def _format_date(value: datetime) -> str:
        return value.strftime("%Y:%m:%d %H:%M:%S")

    @staticmethod
    def _normalize_date(raw_date: object) -> Optional[str]:
        """Return a usable EXIF date, fixing '2026:03:03:12:16:29' -> '2026:03:03 12:16:29'.

        Valid dates come back unchanged, including timezone or subsecond suffixes.
        Missing, blank or placeholder dates such as '0000:00:00 00:00:00' return None.
        """
        if raw_date is None:
            return None
        # exiftool -json emits number-like values unquoted.
        date = str(raw_date)
        parts = date.split(":")
        if len(parts) == 6 and " " not in date:
            date = f"{parts[0]}:{parts[1]}:{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"
        try:
            datetime.strptime(date[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None
        return date

    @staticmethod
    def _fix_dimension(exif_value: Optional[int], actual_value: Optional[int]) -> Optional[int]:
        if actual_value is not None and actual_value > 0 and exif_value != actual_value:
            return actual_value
        return None
