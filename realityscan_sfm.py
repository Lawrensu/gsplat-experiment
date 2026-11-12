"""
Camera poses for a scene with RealityScan, exported as a COLMAP dataset gsplat can train on.

Runs the same RealityScan command and export settings as the Taletoreum pipeline
(src/terrestrial_decolonization/pipeline/realityscan.py): add the frames, optional
AI masks, align, keep the largest component, export COLMAP text with undistorted
PNG images. Reads data/<scene>/frames and writes data/<scene>/colmap with
sparse/0 and images, which is the data_dir for simple_trainer.py.

It also saves the RealityScan project to data/<scene>/realityscan/project.rsproj,
which opens in the RealityScan app to show every camera and the sparse points, so
the parts no camera covers can be seen. Saving is one extra step at the end and
does not change the export.

stump_rs reads stump's own images_4 folder instead of data/stump_rs/frames, so
stump can be trained on RealityScan poses next to its official COLMAP poses.

Needs only the Python standard library, so any of the gsplat conda envs can run it.

Usage:
    python realityscan_sfm.py amorphophallus
    python realityscan_sfm.py stump_rs
    python realityscan_sfm.py amorphophallus --no-masks --force
"""

import argparse
import collections
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path





# RealityScan install folder. The RS_DIR environment variable or --rs-dir overrides it
DEFAULT_RS_DIR = Path("C:/Program Files/Epic Games/RealityScan")
RS_EXE_NAME = "RealityScan.exe"

# Folder layout inside data/<scene>
DATA_ROOT = Path(__file__).resolve().parent / "data"
FRAMES_SUBDIR = "frames"
EXPORT_SUBDIR = "colmap"

# RealityScan's own files: the saved project (with its data folder) and crash reports
PROJECT_SUBDIR = "realityscan"
PROJECT_NAME = "project.rsproj"
CRASH_SUBDIR = "crashreports"

# Scenes whose frames live somewhere other than data/<scene>/frames
FRAMES_OVERRIDES = {
    "stump_rs": DATA_ROOT / "360_v2" / "stump" / "images_4",
}

# Frame file types RealityScan is given
FRAME_SUFFIXES = {".jpg", ".jpeg", ".png"}

# How many frames without a pose the check lists by name
UNREGISTERED_SHOWN = 20

# Watchdog, the same values as Taletoreum: kill RealityScan when it shows no CPU
# or file activity for STALL_TIMEOUT_SECONDS
POLL_INTERVAL_SECONDS = 15
CPU_BUSY_SECONDS = 2.0
STALL_TIMEOUT_SECONDS = 1200
TAIL_LINES = 200

# Export settings, copied unchanged from Taletoreum's realityscan.py. Only
# calexFolder is replaced with the export folder at run time
PARAMS_XML = r"""<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <entry key="calexFolder" value="C:/Temp"/>
  <entry key="calexUndistResMode" value="2"/>
  <entry key="calexUndistPrincipal" value="true"/>
  <entry key="calexTrans" value="1"/>
  <entry key="calexUndistortNaming" value="1"/>
  <entry key="calexUndistortPixelFormat" value="24bppBGR"/>
  <entry key="calexUndistortImageFormat" value="png"/>
  <entry key="calexHasDisabled" value="0x0"/>
  <entry key="calexRequiresUndistortPrincipal" value="0x0"/>
  <entry key="calexExportImages" value="true"/>
  <entry key="MvsExportScaleZ" value="1.0"/>
  <entry key="MvsExportIsGeoreferenced" value="0x1"/>
  <entry key="MvsExportIsModelCoordinates" value="0"/>
  <entry key="colmapDirStructure" value="0"/>
  <entry key="calexRequiresColorCorrection" value="0x1"/>
  <entry key="MvsExportScaleY" value="1.0"/>
  <entry key="calexRequiresEqualResolution" value="0x0"/>
  <entry key="calexDownscale" value="0x1"/>
  <entry key="calexUndistMaxPixels" value="0x0"/>
  <entry key="calexInputHasLayers" value="1"/>
  <entry key="calexCorrectColors" value="true"/>
  <entry key="MvsExportScaleX" value="1.0"/>
  <entry key="calexUndistFitMode" value="4"/>
  <entry key="MvsExportRotationY" value="0.0"/>
  <entry key="MvsExportcoordinatesystemtype" value="0"/>
  <entry key="MvsExportNormalFlipZ" value="false"/>
  <entry key="MvsExportRotationX" value="0.0"/>
  <entry key="calexFolderCustom" value="true"/>
  <entry key="hasCalexFilePath" value="1"/>
  <entry key="MvsExportNormalFlipY" value="false"/>
  <entry key="MvsExportNormalSpace" value="Mikktspace"/>
  <entry key="calexHasUndistort" value="1"/>
  <entry key="colmapExportMasks" value="false"/>
  <entry key="MvsExportNormalFlipX" value="false"/>
  <entry key="MvsExportRotationZ" value="0.0"/>
  <entry key="calexExportUndistorted" value="true"/>
  <entry key="colmapFileType" value="CFT_TXT"/>
  <entry key="calexFileFormat" value="COLMAP"/>
  <entry key="MvsExportMoveZ" value="0.0"/>
  <entry key="calexFileFormatId" value="{280B11A4-F9A3-47D1-AE58-C0DEA33487D8}"/>
  <entry key="calexImageLayerOptions" value="0"/>
  <entry key="calexUndistBackColor" value="0"/>
  <entry key="hasRadianceFieldsTransAABB" value="0"/>
  <entry key="hasCalexFileName" value="1"/>
  <entry key="calexUndistCutOut" value="1.0"/>
  <entry key="calexHasImageExport" value="1"/>
  <entry key="MvsExportMoveX" value="0.0"/>
  <entry key="MvsExportNormalRange" value="ZeroToOne"/>
  <entry key="MvsExportMoveY" value="0.0"/>
</Configuration>
"""





class FILETIME(ctypes.Structure):
    """
    Win32 FILETIME, a 64 bit count of 100 nanosecond ticks, read through GetProcessTimes.
    """

    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]



def process_cpu_seconds(handle: int) -> float:
    """
    Total CPU time a Windows process has used, kernel plus user.

    Args:
        handle: Win32 process handle

    Returns:
        CPU seconds, or 0.0 when the call fails
    """
    creation, exit_time, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    ok = ctypes.windll.kernel32.GetProcessTimes(
        handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        return 0.0

    def to_seconds(ft: FILETIME) -> float:
        return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 10_000_000.0

    return to_seconds(kernel) + to_seconds(user)



def newest_mtime(directory: Path) -> float:
    """
    Newest file modification time under a folder, used as a sign that the export is writing.

    Args:
        directory: folder to scan

    Returns:
        newest mtime, or 0.0 when the folder has no files
    """
    newest = 0.0
    for path in directory.rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return newest





def write_params_xml(export_dir: Path) -> Path:
    """
    Write the export settings with calexFolder set to the export folder.

    Args:
        export_dir: folder RealityScan exports the COLMAP dataset into

    Returns:
        path of the written params.xml
    """
    root = ET.fromstring(PARAMS_XML)
    for entry in root.iter("entry"):
        if entry.attrib.get("key") == "calexFolder":
            entry.set("value", export_dir.as_posix() + "/")
            break
    else:
        raise RuntimeError("calexFolder not found in PARAMS_XML")

    params_path = export_dir / "params.xml"
    ET.ElementTree(root).write(params_path, encoding="utf-8", xml_declaration=True)
    return params_path



def build_command(rs_exe: Path, frames_dir: Path, export_dir: Path, params_xml: Path, crash_dir: Path, project_path: Path, masks: bool) -> list[str]:
    """
    The RealityScan command line, the same steps as Taletoreum plus -save for the project.

    Args:
        rs_exe: path of RealityScan.exe
        frames_dir: folder with the input frames
        export_dir: folder for the COLMAP export
        params_xml: export settings file
        crash_dir: folder for RealityScan crash reports
        project_path: .rsproj file the aligned project is saved to
        masks: add -generateAIMasks before aligning

    Returns:
        command as a list of arguments
    """
    cmd = [
        str(rs_exe), "-headless", "-silent", str(crash_dir),
        "-set", "appQuitOnError=true", "-stdConsole",
        "-newScene", "-addFolder", str(frames_dir),
        "-align", "-selectMaximalComponent",
        "-exportRegistration", str(export_dir), str(params_xml),
        "-save", str(project_path),
        "-quit",
    ]
    if masks:
        cmd.insert(cmd.index("-align"), "-generateAIMasks")
    return cmd



def run_realityscan(cmd: list[str], export_dir: Path) -> None:
    """
    Run RealityScan, echo its console, and kill it when it stalls.

    Progress means the process CPU time rising by CPU_BUSY_SECONDS or a newer file
    in the export folder. With neither for STALL_TIMEOUT_SECONDS the process is killed.

    Args:
        cmd: command from build_command
        export_dir: folder watched for new files

    Returns:
        None. Raises RuntimeError on a stall or a non zero exit code
    """
    tail = collections.deque(maxlen=TAIL_LINES)

    def echo(stream) -> None:
        for line in iter(stream.readline, ""):
            tail.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace") as proc:
        threading.Thread(target=echo, args=(proc.stdout,), daemon=True).start()
        last_cpu = process_cpu_seconds(proc._handle)
        last_mtime = newest_mtime(export_dir)
        last_progress = time.monotonic()

        while proc.poll() is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            cpu = process_cpu_seconds(proc._handle)
            mtime = newest_mtime(export_dir)
            if cpu - last_cpu >= CPU_BUSY_SECONDS or mtime > last_mtime:
                last_cpu, last_mtime, last_progress = cpu, mtime, time.monotonic()
            elif time.monotonic() - last_progress >= STALL_TIMEOUT_SECONDS:
                proc.kill()
                raise RuntimeError(f"RealityScan showed no activity for {STALL_TIMEOUT_SECONDS} s and was stopped")

        if proc.returncode != 0:
            raise RuntimeError(f"RealityScan exited with code {proc.returncode}")





def read_colmap_lines(path: Path) -> list[str]:
    """
    Non comment, non empty lines of a COLMAP text file.

    Args:
        path: cameras.txt, images.txt or points3D.txt

    Returns:
        the data lines, in order
    """
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip() and not line.startswith("#")]



def validate_export(export_dir: Path, frames: list[Path]) -> None:
    """
    Check the COLMAP export is complete and print what it holds.

    Reads the text files directly, so it works in any env. images.txt has two lines
    per image: the pose line, then the 2D points line, which can be empty, so the
    pose lines are found by their 10 fields ending in the image name.

    Args:
        export_dir: folder with sparse/0 and images
        frames: input frames, to report which ones got no pose

    Returns:
        None. Raises RuntimeError when a file or a registered image is missing
    """
    sparse = export_dir / "sparse" / "0"
    images_dir = export_dir / "images"
    for needed in (sparse / "cameras.txt", sparse / "images.txt", sparse / "points3D.txt", images_dir):
        if not needed.exists():
            raise RuntimeError(f"Missing from the export: {needed}")

    cameras = read_colmap_lines(sparse / "cameras.txt")
    points = read_colmap_lines(sparse / "points3D.txt")
    names = []
    with open(sparse / "images.txt", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if not line.startswith("#")]
    for pose_line in lines[0::2]:
        fields = pose_line.split()
        if len(fields) >= 10:
            names.append(" ".join(fields[9:]))

    if not names:
        raise RuntimeError("RealityScan registered no images")
    missing = [n for n in names if not (images_dir / n).is_file()]
    if missing:
        raise RuntimeError(f"{len(missing)} registered images are missing from {images_dir}, for example {missing[:3]}")

    print()
    print(f"Export OK: {export_dir}")
    print(f"  registered images: {len(names)} of {len(frames)} frames")
    print(f"  3D points:         {len(points)}")

    # The export renames frames to .png, so compare by name without the extension
    registered = {Path(n).stem for n in names}
    unregistered = sorted(p.name for p in frames if p.stem not in registered)
    if unregistered:
        shown = ", ".join(unregistered[:UNREGISTERED_SHOWN])
        more = f" and {len(unregistered) - UNREGISTERED_SHOWN} more" if len(unregistered) > UNREGISTERED_SHOWN else ""
        print(f"  frames with no pose: {shown}{more}")

    # The undistorted export gives each image its own camera with its own crop, so summarise
    models = sorted({cam.split()[1] for cam in cameras})
    widths = [int(cam.split()[2]) for cam in cameras]
    heights = [int(cam.split()[3]) for cam in cameras]
    print(f"  cameras:           {len(cameras)} ({', '.join(models)})")
    print(f"  image sizes:       {min(widths)}x{min(heights)} to {max(widths)}x{max(heights)}")





def main() -> int:
    """
    Parse the arguments, run RealityScan for one scene and validate the export.

    Returns:
        process exit code, 0 on success
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene", help="folder name under data, for example amorphophallus or stump_rs")
    parser.add_argument("--rs-dir", type=Path, default=Path(os.environ.get("RS_DIR", DEFAULT_RS_DIR)), help="RealityScan install folder")
    parser.add_argument("--no-masks", action="store_true", help="align without -generateAIMasks")
    parser.add_argument("--force", action="store_true", help="delete the existing export and project and run again")
    args = parser.parse_args()

    scene_dir = DATA_ROOT / args.scene
    frames_dir = FRAMES_OVERRIDES.get(args.scene, scene_dir / FRAMES_SUBDIR)
    export_dir = scene_dir / EXPORT_SUBDIR
    project_dir = scene_dir / PROJECT_SUBDIR
    project_path = project_dir / PROJECT_NAME
    crash_dir = project_dir / CRASH_SUBDIR
    rs_exe = args.rs_dir / RS_EXE_NAME

    if not rs_exe.is_file():
        print(f"ERROR: {rs_exe} not found. Pass --rs-dir or set RS_DIR to the RealityScan folder")
        return 1
    frames = [p for p in frames_dir.glob("*") if p.suffix.lower() in FRAME_SUFFIXES] if frames_dir.is_dir() else []
    if not frames:
        print(f"ERROR: no frames in {frames_dir}")
        return 1

    if export_dir.exists():
        if not args.force:
            print(f"An export already exists at {export_dir}. Checking it. Add --force to run RealityScan again")
            validate_export(export_dir, frames)
            print(f"  project:           {project_path if project_path.is_file() else 'not saved'}")
            return 0
        shutil.rmtree(export_dir)
    if project_dir.exists() and args.force:
        shutil.rmtree(project_dir)
    export_dir.mkdir(parents=True)
    crash_dir.mkdir(parents=True, exist_ok=True)

    params_xml = write_params_xml(export_dir)
    cmd = build_command(rs_exe, frames_dir, export_dir, params_xml, crash_dir, project_path, masks=not args.no_masks)
    print(f"RealityScan on {len(frames)} frames from {frames_dir}, AI masks {'off' if args.no_masks else 'on'}")
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    print()
    started = time.monotonic()
    run_realityscan(cmd, export_dir)
    print(f"RealityScan finished in {(time.monotonic() - started) / 60:.1f} min")

    validate_export(export_dir, frames)
    if project_path.is_file():
        print(f"  project:           {project_path}")
        print("  Open it in RealityScan to see the cameras and the sparse points")
    else:
        print(f"  WARNING: the project was not saved to {project_path}. The export is still fine")
    return 0





if __name__ == "__main__":
    sys.exit(main())
