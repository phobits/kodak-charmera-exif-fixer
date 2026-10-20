import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from kodak_charmera.core.exif_fixer import ExifFixer
from kodak_charmera.core.models import CameraFile, ExifData, FileType
from kodak_charmera.core.scanner import CameraScanner


class CameraMetadataTests(unittest.TestCase):
    def setUp(self):
        self.exif = Mock()
        self.scanner = CameraScanner(Mock(), self.exif)

    def test_missing_camera_alone_triggers_repair(self):
        fix = self.scanner._compute_exif_fix(ExifData())
        self.assertTrue(fix.has_fixes)
        self.assertEqual((fix.fixed_make, fix.fixed_model), ('Kodak', 'Charmera'))
        file = CameraFile(Path('source.jpg'), FileType.PHOTO, 1, datetime.now(),
                          exif_fix=fix, destination_path=Path('copy.jpg'))
        self.exif.read_exif.return_value = ExifData(
            make='Kodak', model='Charmera', lens_model=fix.fixed_lens_model,
            f_number=fix.fixed_f_number, focal_length=fix.fixed_focal_length,
            focal_length_35mm=fix.fixed_focal_length_35mm,
            user_comment=fix.fixed_user_comment)
        ExifFixer(self.exif).fix(file)
        values = self.exif.write_exif.call_args.args[1]
        self.assertEqual((values['make'], values['model']), ('Kodak', 'Charmera'))

    def test_correct_camera_needs_no_repair(self):
        self.assertFalse(self.scanner._compute_exif_fix(
            ExifData(make='Kodak', model='Charmera', lens_model='Existing lens', f_number=2.4,
                     focal_length=35.0, focal_length_35mm=35)).has_fixes)

    def test_chipset_metadata_is_replaced(self):
        fix = self.scanner._compute_exif_fix(ExifData(make='Generalplus', model='CBB3'))
        self.assertEqual((fix.fixed_make, fix.fixed_model), ('Kodak', 'Charmera'))

    def test_failed_camera_write_is_rejected(self):
        file = CameraFile(Path('source.jpg'), FileType.PHOTO, 1, datetime.now(),
                          exif_fix=self.scanner._compute_exif_fix(ExifData()),
                          destination_path=Path('copy.jpg'))
        self.exif.read_exif.return_value = ExifData()
        with self.assertRaisesRegex(RuntimeError, 'verification failed for make'):
            ExifFixer(self.exif).fix(file)

    def test_existing_lens_and_aperture_are_preserved(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            lens_model='Recorded lens', f_number=2.8, focal_length=35.0, focal_length_35mm=35,
            user_comment='Personal note'))
        self.assertIsNone(fix.fixed_lens_model)
        self.assertIsNone(fix.fixed_f_number)
        self.assertIsNone(fix.fixed_user_comment)

    def test_provenance_preserves_comment_and_missing_dimensions_are_filled(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            user_comment='Personal note', actual_image_width=1440, actual_image_height=1080))
        self.assertTrue(fix.fixed_user_comment.startswith('Personal note\n'))
        self.assertIn('not measured exposure', fix.fixed_user_comment)
        self.assertEqual((fix.fixed_exif_image_width, fix.fixed_exif_image_height), (1440, 1080))

    def test_missing_dates_are_taken_from_file_time(self):
        fix = self.scanner._compute_exif_fix(ExifData(), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(
            (fix.fixed_modify_date, fix.fixed_datetime_original, fix.fixed_create_date),
            ('2026:10:03 13:52:32',) * 3)
        self.assertTrue(fix.dates_from_file_time)
        self.assertIn('file modification time', fix.fixed_user_comment)

    def test_placeholder_dates_count_as_missing(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            modify_date='0000:00:00 00:00:00', datetime_original='    :  :     :  :  ',
            create_date=''), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(fix.fixed_datetime_original, '2026:10:03 13:52:32')
        self.assertEqual(fix.fixed_modify_date, '2026:10:03 13:52:32')
        self.assertTrue(fix.dates_from_file_time)

    def test_camera_date_fills_sibling_fields_before_file_time(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            datetime_original='2026:03:03 12:16:29', lens_model='Recorded lens', f_number=2.4,
            focal_length=35.0, focal_length_35mm=35), datetime(2026, 10, 3, 13, 52, 32))
        self.assertIsNone(fix.fixed_datetime_original)
        self.assertEqual((fix.fixed_modify_date, fix.fixed_create_date),
                         ('2026:03:03 12:16:29',) * 2)
        self.assertFalse(fix.dates_from_file_time)
        self.assertIsNone(fix.fixed_user_comment)

    def test_malformed_camera_dates_win_over_file_time(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            modify_date='2026:03:03:12:16:29', datetime_original='2026:03:03:12:16:29',
            create_date='2026:03:03:12:16:29'), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(fix.fixed_datetime_original, '2026:03:03 12:16:29')
        self.assertFalse(fix.dates_from_file_time)
        self.assertNotIn('file modification time', fix.fixed_user_comment)

    def test_valid_dates_are_left_alone(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            modify_date='2026:03:03 12:16:29', datetime_original='2026:03:03 12:16:29',
            create_date='2026:03:03 12:16:29'), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(
            (fix.fixed_modify_date, fix.fixed_datetime_original, fix.fixed_create_date),
            (None, None, None))

    def test_missing_focal_length_gets_35mm_equivalent(self):
        fix = self.scanner._compute_exif_fix(ExifData())
        self.assertEqual((fix.fixed_focal_length, fix.fixed_focal_length_35mm), (35, 35))
        self.assertIn('35mm-equivalent', fix.fixed_user_comment)
        for recorded in (ExifData(focal_length=4.0), ExifData(focal_length_35mm=28),
                         ExifData(focal_length=4.0, focal_length_35mm=0)):
            fix = self.scanner._compute_exif_fix(recorded)
            self.assertEqual((fix.fixed_focal_length, fix.fixed_focal_length_35mm), (None, None))
        fix = self.scanner._compute_exif_fix(ExifData(focal_length_35mm=35))
        self.assertEqual((fix.fixed_focal_length, fix.fixed_focal_length_35mm), (35.0, None))

    def test_date_only_note_has_no_lens_source(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            lens_model='Recorded lens', f_number=2.4, focal_length=35.0, focal_length_35mm=35),
            datetime(2026, 10, 3, 13, 52, 32))
        self.assertIn('file modification time', fix.fixed_user_comment)
        self.assertNotIn('Source:', fix.fixed_user_comment)

    def test_dates_with_timezone_are_kept(self):
        fix = self.scanner._compute_exif_fix(ExifData(
            modify_date='2026:03:03 12:16:29+02:00', datetime_original='2026:03:03 12:16:29.50',
            create_date='2026:03:03 12:16:29'), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(
            (fix.fixed_modify_date, fix.fixed_datetime_original, fix.fixed_create_date),
            (None, None, None))

    def test_numeric_date_value_counts_as_missing(self):
        fix = self.scanner._compute_exif_fix(ExifData(datetime_original=0),
                                             datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(fix.fixed_datetime_original, '2026:10:03 13:52:32')

    def test_zero_focal_length_counts_as_unknown(self):
        self.assertEqual(self.scanner._compute_exif_fix(
            ExifData(focal_length=0, focal_length_35mm=0)).fixed_focal_length_35mm, 35)

    def test_modify_date_never_becomes_capture_date(self):
        fix = self.scanner._compute_exif_fix(ExifData(modify_date='2026:10:19 08:00:00'),
                                             datetime(2026, 10, 3, 13, 52, 32))
        self.assertIsNone(fix.fixed_modify_date)
        self.assertEqual((fix.fixed_datetime_original, fix.fixed_create_date),
                         ('2026:10:03 13:52:32',) * 2)
        self.assertTrue(fix.dates_from_file_time)

    def test_rerun_replaces_old_fixer_note(self):
        old = ('Personal note\nCharmera EXIF Fixer: LensModel is a descriptive label; '
               'FNumber=2.4 is the nominal manufacturer aperture, not measured exposure. '
               'Manufacturer lists lens as 35mm F2.4; focal length fields are not inferred. '
               'Source: https://example.invalid')
        fix = self.scanner._compute_exif_fix(ExifData(
            lens_model='Kodak Charmera built-in lens', f_number=2.4, user_comment=old,
            datetime_original='2026:03:03 12:16:29', create_date='2026:03:03 12:16:29',
            modify_date='2026:03:03 12:16:29'))
        comment = fix.fixed_user_comment
        self.assertTrue(comment.startswith('Personal note\nCharmera EXIF Fixer: '))
        self.assertEqual(comment.count('Charmera EXIF Fixer:'), 1)
        self.assertIn('LensModel is a descriptive label', comment)
        self.assertIn('FocalLength/FocalLengthIn35mmFormat=35', comment)
        self.assertNotIn('not inferred', comment)

    def test_rerun_on_fixed_photo_changes_nothing(self):
        first = self.scanner._compute_exif_fix(ExifData(), datetime(2026, 10, 3, 13, 52, 32))
        fixed = ExifData(**{name: value for name, value in first.values().items()})
        self.assertFalse(self.scanner._compute_exif_fix(
            fixed, datetime(2026, 10, 3, 13, 52, 32)).has_fixes)

    def test_labels_are_shared_by_presenters(self):
        fix = self.scanner._compute_exif_fix(ExifData(), datetime(2026, 10, 3, 13, 52, 32))
        self.assertEqual(fix.labels(), ['lens: manufacturer data', 'camera: Kodak Charmera',
                                        'date from file time'])

    def test_note_rewrite_keeps_user_text_and_drops_every_old_note(self):
        old = ('Personal note\n\n'
               'Charmera EXIF Fixer: the camera wrote no capture date, so all dates were taken '
               'from the file modification time.\n'
               'Charmera EXIF Fixer: FocalLength/FocalLengthIn35mmFormat=35 is the advertised '
               '35mm-equivalent, written to FocalLength for display; the actual focal length '
               'of the 1/4-inch sensor lens is shorter. Manufacturer lists lens as 35mm F2.4.\n'
               'later text')
        note = self.scanner._merge_note(old, {'lens'})
        user, _, fixer = note.rpartition('\n')
        self.assertEqual(user, 'Personal note\n\nlater text')
        self.assertEqual(fixer.count('Charmera EXIF Fixer:'), 1)
        self.assertNotIn('; the actual', fixer)
        for clause in ('LensModel is', 'FocalLength/', 'file modification time'):
            self.assertIn(clause, fixer)

    def test_comment_only_fix_has_a_label(self):
        from kodak_charmera.core.models import ExifFix
        self.assertEqual(ExifFix(fixed_user_comment='x').labels(), ['provenance note'])
