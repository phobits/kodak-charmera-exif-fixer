from .models import CameraFile, ProcessingStatus
from ..ports.exiftool_port import ExiftoolPort


class ExifFixer:

    def __init__(self, exiftool: ExiftoolPort):
        self._exiftool = exiftool

    def fix(self, file: CameraFile) -> CameraFile:
        fix = file.exif_fix
        if fix is None or not fix.has_fixes:
            file.status = ProcessingStatus.COMPLETED
            return file

        assert file.destination_path is not None
        file.status = ProcessingStatus.FIXING_EXIF
        values = fix.values()
        self._exiftool.write_exif(file.destination_path, values)
        actual = self._exiftool.read_exif(file.destination_path)
        for field, expected in values.items():
            if getattr(actual, field) != expected:
                raise RuntimeError(f"EXIF verification failed for {field}")
        file.status = ProcessingStatus.COMPLETED
        return file
