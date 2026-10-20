# Review and Improvement Plan

> Historical review written before the subsequent changes. Since then, overwrite
> prompts, temporary processing and output validation, label-independent card
> discovery, recursive scanning, camera tags, capture-date and focal-length filling,
> and a compact CLI progress display have been added, among other things. Tests live
> in `tests/`. The findings and test-bench notes below describe the state at the time,
> not necessarily the current code; further planning items remain open.

As of: 6 September 2026. Subject is the local repository state, without changes to the application code and without processing personal camera files.

## Assessment

The separation of core logic, tool adapters and user interface is a usable foundation. A complete rewrite is not needed. Before regular imports, however, overwrite protection, error handling and verifiable metadata correction should be implemented.

What matters for the concrete Charmera problem: for photos, the current code only repairs one particular date format and mismatched EXIF dimensions that are already present. It does not correct a wrongly set camera clock, missing date values or a time offset. Whether the implementation matches this camera's actual defects still has to be checked against unmodified sample files.

## Findings by Priority

### P1: Existing videos can be overwritten

Locations: `core/file_copier.py:25`, `core/video_converter.py:22`, `adapters/ffmpeg_cli.py:33`.

The copier only checks the AVI target name. After a successful conversion the AVI copy is deleted by default. On the next import that name is free again, although the MP4 still exists. The converter uses the same MP4 name and FFmpeg is passed `-y`. The existing MP4 is therefore overwritten; different videos with the same modification time are affected too. The target collision was reproduced with temporary files and a simulated FFmpeg adapter.

Remedy: reserve all final target names collision-free up front, never overwrite existing outputs implicitly, and detect repeated imports via content checksums. With parallel processes a plain `exists()` check is not enough.

### P1: Video conversion can hang indefinitely

Location: `adapters/ffmpeg_cli.py:46`.

The adapter reads stdout continuously, but stderr only after the process has ended and only on errors. With enough diagnostic output the stderr pipe can fill up: FFmpeg waits for a reader while the application waits for further progress. A timeout and an orderly shutdown of the child process are missing.

Remedy: drain both streams concurrently or redirect stderr to a temporary log file; add bounded diagnostic output, a cancellation signal and reliable cleanup. Finding from code inspection, not from a real long-running conversion test.

### P2: A single read error blocks the entire import

Location: `core/scanner.py:32`.

File stats and EXIF reading run without per-file error handling. A single corrupt JPEG, or a file removed during the scan, prevents the preview of all otherwise readable files. Reproduced with an EXIF adapter that raises an exception for one file.

Remedy: collect read errors per file as part of the scan result; keep offering readable files. Report missing tools separately before the scan.

### P2: Media in DCIM subfolders are missed

Location: `core/scanner.py:23`.

The scanner calls `list_files()` without recursion; the filesystem adapter defaults to `recursive=False`. A file at `DCIM/100MEDIA/photo.jpg` therefore yields zero hits. Reproduced with a temporary directory structure.

Remedy: scan recursively and deterministically, exclude metadata files, and define symlink handling explicitly.

### P2: Structural defects alone do not trigger an EXIF repair

Locations: `core/models.py:23`, `core/scanner.py:56`, `core/exif_fixer.py:12`.

EXIF warnings and structural defects are not captured in the data model. If date and dimensions look fine, the fixer skips processing entirely, even when a structural defect is present. Conversely, every simple tag correction rebuilds the whole metadata structure. After writing, the actual tags are not checked.

Remedy: model diagnosis and value corrections separately, trigger structural repair deliberately, and compare metadata before and after writing. Which damaged tags can actually be recovered must be tested on original files; full preservation has not been demonstrated so far.

### P2: Invalid date values are proposed as corrections

Location: `core/scanner.py:66`.

The detection only counts colon-separated parts. Even `2026:99:99:25:61:61` becomes a supposedly corrected date. Missing values, and values that are formally valid but factually wrong, stay unchanged. Videos take the file modification time as capture time without checks; the filesystem adapter returns a timestamp without a time zone.

Remedy: validate calendar values strictly, show the date source and its uncertainty. Provide a manual clock correction and camera time zone; do not pretend certainty when the capture time is unknown. Check video time metadata after writing, with an explicitly defined time-zone strategy.

### P2: Automation reports success despite processing errors

Locations: `core/pipeline.py:83`, `__main__.py:33`.

The pipeline collects errors, but `_run_pipeline()` discards its results. The CLI process can exit normally with exit code 0 when files failed. An empty scan is not passed on as an error status either.

Remedy: a structured overall result and documented exit codes for success, partial failure and startup failure. Handle cancellation by the user separately.

### P2: The GUI error display can stop further UI updates

Location: `ui/tkinter_app.py:53`.

The deferred lambda accesses the exception variable `e`. Python deletes it after the `except` block. If the callback runs afterwards, a `NameError` is raised; `_poll_queue()` only catches `queue.Empty` and then schedules no further poll.

Remedy: store the error text beforehand or bind it to the callback, and guard queue processing against individual callback errors. Checked statically; the active Python interpreter has no `_tkinter`, so no GUI runtime test.

## Further Improvements

- In the GUI, `--dest` is overridden by its built-in default and the value read at startup. Initialise the UI from the ProcessingPlan.
- Without a detected camera, the GUI message is only queued and the app then exits before the event loop starts. Offer a visible empty state with source selection.
- The source is fixed to `/Volumes/Untitled/DCIM`. `--source` and a folder picker would also allow SD cards with other names and photos that were already copied.
- Closing the window ends the background thread without a controlled abort. Temporary outputs and child processes need orderly cleanup.
- The application writes directly to the final files. Failed repairs can leave half-finished results. AVI copies are deleted without additional output validation.
- Nothing prevents a chosen destination from lying on the camera volume. That contradicts the documented promise not to modify anything there.
- Repeated photo imports keep producing further copies. An import manifest should store source checksum, target, repair version and result.
- The LaunchAgent loads its template from a path outside the Python package; the package configuration contains no corresponding resource. Test a wheel installation including the launcher and ship the template as a package resource.
- Several configuration fields, such as `dcim_subdir` and the file extensions, are not used by the scanner.
- Each photo spawns one read process and, when repaired, two write processes. Measure only after correctness is secured, and use ExifTool batches if needed.

## Implementation Plan

### 1. Prevent data loss and blocking processes

Collision-free target planning for AVI and MP4, temporary working files, publishing only after successful validation, orderly process cancellation and safe stderr handling. Keep unmodified original copies for now; offer deletion as an explicit option. Validate source and destination before processing.

Acceptance: two videos with the same timestamp do not overwrite each other; a repeated import does not change existing outputs. Cancellation, a full disk and tool errors leave no partial file marked as finished. Sources stay byte-identical. Heavy stderr output does not cause a stall.

### 2. Make the EXIF repair sound

Build a small reference set of unmodified Charmera JPEGs and AVIs. Record raw metadata and warnings. Implement strict date validation, an explicit date source, optional clock correction and time zone. Separate structural repair from tag changes and read the results back. Fill missing dimensions from verified image dimensions.

Acceptance: expected changes are defined for every reference file. Correct metadata is preserved; JPEG image data is not recompressed. A second repair pass produces no further changes. Unknown capture times are shown as unresolved.

### 3. Make everyday imports reliable

Implement free source selection, recursive scanning, per-file error isolation, dependency checks, an import manifest and exit codes. Update the manifest only after validated publishing; detect missing or changed target outputs on restart.

Acceptance: a renamed SD card and a local folder work. A broken file does not block healthy files. A repeat run skips verified imports. Partial failures are unambiguous for CLI automation.

### 4. Round off the interface and distribution

Preview with old/new values and date source, file selection, visible per-file errors, safe cancellation and correct use of the destination folder. Check package resources and the launcher. Then measure run times on a defined set of media and optimise only proven bottlenecks.

Acceptance: source, destination and planned changes are visible before starting. Errors do not freeze the interface. Installation from a built wheel works independently of the repository directory.

## Test Bench and Limits

- Read all Python application code, the README, the package configuration and the LaunchAgent configuration.
- `python3 -m unittest discover -v`: 0 tests; `tests/` only contains `__init__.py`.
- Ran temporary reproductions for the MP4 target collision, missing output validation before AVI deletion, the non-recursive scan, the scan abort and insufficient date validation, with external adapters simulated.
- ExifTool, FFmpeg and ffprobe are installed locally, but were not validated with real camera files in this review.
- GUI execution was not possible because the active Python lacks `_tkinter`. No statement about GUI or media integration that may already have been tested successfully.
- No changes to the application code; this document records the review and the plan.
