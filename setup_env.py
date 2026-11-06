"""Set up the Python side of one gsplat version on the Windows lab PC (no admin).

Runs inside the activated conda env (setup.bat does that and creates the env).
Stdlib only at top level. Every step checks first and only installs what is
missing, so reruns are fast.

Usage: python setup_env.py {153,160}      set up one version (steps 2 to 9 of 9)
       python setup_env.py summary {153,160}   print a short status block (no imports of torch or gsplat)

Follows the official gsplat route: docs/INSTALL_WIN.md option 4 (clone --recursive,
MSVC environment, pip install, CUDA compiled at install) and the README evaluation
section (pip install -e ., then pip install -r examples/requirements.txt).
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path




# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CU128_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_VERSION = "2.9.1"
TORCHVISION_VERSION = "0.24.1"

GSPLAT_URL = "https://github.com/nerfstudio-project/gsplat.git"

# key: what the user types after setup.bat. numpy: the pin the version's own
# examples/requirements.txt uses, so the build dependencies do not fight it.
# experimental: setup.py builds a second extension (gsplat.experimental) by default.
VERSIONS = {
    "153": {
        "label": "1.5.3",
        "sha": "937e29912570c372bed6747a5c9bf85fed877bae",
        "folder": "gsplat-1.5.3",
        "env": "gsplat153",
        "numpy": "numpy<2.0.0",
        "experimental": False,
    },
    "160": {
        "label": "1.6.0",
        "sha": "512d366b67073d77ca099ede742683c165dfc23b",
        "folder": "gsplat-1.6.0",
        "env": "gsplat160",
        "numpy": "numpy>=2.0,<3.0",
        "experimental": True,
    },
}

EXP_DIR = Path(__file__).resolve().parent
TOOLS_DIR = EXP_DIR / "tools"
PATCH_DIR = EXP_DIR / "patches"
PATCH_MARKER = "gsplat Windows patch"
MSVC_ENV_FILE = TOOLS_DIR / "msvc_env.txt"
PORTABLE_MSVC_BAT = TOOLS_DIR / "msvc" / "setup_x64.bat"
GLM_HEADER_REL = "gsplat/cuda/csrc/third_party/glm/glm/glm.hpp"

# Community script that downloads MSVC from Microsoft and extracts it without admin rights
# (gist by mmozeiko). Pinned to one revision and checked by hash before it is run.
MSVC_SCRIPT_URL = (
    "https://gist.githubusercontent.com/mmozeiko/7f3162ec2988e81e56d5c4e22cde9977/raw/"
    "553d55bb7f0405a2fbd0228b8ed87c2b8ad200f8/portable-msvc.py"
)
MSVC_SCRIPT_SHA256 = "1791cccca594ff083ce8d3e0a139e6156d2c312e24332a909e608010f0230a51"
MSVC_SCRIPT_PATH = TOOLS_DIR / "portable-msvc.py"
MSVC_VERSION = "14.44"  # the newest toolset CUDA 12.8 supports

# Entries of examples/requirements.txt that simple_trainer.py imports lazily, only on
# options the COLMAP baseline does not use. They are the only entries the retry may drop,
# and only when pip's own output names them as the failure.
#   nvidia-ncore:   datasets.ncore, only when --data_type ncore
#   ppisp:          only with --post_processing ppisp
#   fused-bilagrid: only with --use_fused_bilagrid (1.5.3) or --post_processing bilateral_grid (1.6.0)
OPTIONAL_REQS = {
    "nvidia-ncore": "NCore dataset example only",
    "ppisp": "only --post_processing ppisp",
    "fused-bilagrid": "only the fused bilateral grid option",
}

TOTAL_STEPS = 9




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def step(i, total, title):
    print()
    print(f"[{i}/{total}] {title}")


def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def pip(*args, cwd=None, env=None):
    cmd = [sys.executable, "-m", "pip", *args]
    print("  >", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=cwd, env=env)


def pip_or_fail(*args, cwd=None, env=None):
    try:
        pip(*args, cwd=cwd, env=env)
    except subprocess.CalledProcessError:
        fail("pip failed (see output above). Send the last 40 lines of this window.")


def pip_capture(*args, cwd=None, env=None):
    """Run pip, show its output live and also return (exit code, full text)."""
    cmd = [sys.executable, "-m", "pip", *args]
    print("  >", " ".join(cmd))
    p = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    lines = []
    for line in p.stdout:
        lines.append(line)
        try:
            print(line, end="", flush=True)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"), end="", flush=True)
    p.wait()
    return p.returncode, "".join(lines)


LOGS_DIR = Path(__file__).resolve().parent / "logs"
ERROR_RE = re.compile(
    r"(error|fatal|failed:|cannot open|no such file|unresolved external|is not recognized)", re.I)


def save_failure_log(name, text):
    """Write the full output to logs/<name>.log and print the lines that name the error.

    pip -v prints thousands of lines and ends with a generic "Failed building wheel",
    so the compiler message that explains the failure is easy to miss.
    """
    LOGS_DIR.mkdir(exist_ok=True)
    path = LOGS_DIR / f"{name}.log"
    path.write_text(text, encoding="utf-8", errors="replace")
    hits, seen = [], set()
    for line in text.splitlines():
        s = line.strip()
        if ERROR_RE.search(s) and s not in seen:
            seen.add(s)
            hits.append(s)
    print()
    print(f"  Full output saved to {path}")
    if hits:
        print("  First lines that mention an error:")
        for s in hits[:25]:
            print("   |", s[:300])
    return path


def run_py(code, cwd=None, capture=True):
    """Run code in a fresh interpreter so a broken import cannot kill this script."""
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, capture_output=capture, text=True,
        errors="replace",
    )


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_available(name):
    import importlib.util
    return importlib.util.find_spec(name) is not None


def lib_dir():
    """The conda Library folder, which is where the conda CUDA toolkit lives on Windows."""
    return Path(sys.prefix) / "Library"


def prepend_path(var, dirs):
    """Put existing dirs at the front of a ';' separated variable, without duplicates."""
    parts = [p for p in os.environ.get(var, "").split(";") if p]
    have = {os.path.normcase(os.path.normpath(p)) for p in parts}
    new = []
    for d in dirs:
        d = Path(d)
        if d.is_dir() and os.path.normcase(os.path.normpath(str(d))) not in have:
            new.append(str(d))
    if new:
        os.environ[var] = ";".join(new + parts)


def conda_exe():
    exe = os.environ.get("CONDA_EXE")
    if exe and Path(exe).exists():
        return exe
    found = shutil.which("conda")
    if not found:
        fail("conda not found (CONDA_EXE is not set). Run this through setup.bat.")
    return found


def conda_install(*pkgs):
    cmd = [conda_exe(), "install", "-y", "-p", sys.prefix,
           "-c", "conda-forge", "--override-channels", *pkgs]
    print("  >", " ".join(cmd))
    return subprocess.run(cmd).returncode == 0


def nvcc_is_128():
    nvcc = lib_dir() / "bin" / "nvcc.exe"
    if not nvcc.exists():
        return False
    try:
        r = subprocess.run([str(nvcc), "--version"], capture_output=True, text=True)
    except OSError:
        return False
    return "release 12.8" in r.stdout


def download(url, dest):
    cmd = ["curl.exe", "-L", "--fail", "-o", str(dest), url]
    print("  >", " ".join(cmd))
    if subprocess.run(cmd).returncode != 0:
        fail(f"download failed: {url}")


def download_verified(url, dest, sha256):
    """Download url to dest and check its sha256. A file with the right hash is reused."""
    dest = Path(dest)
    if dest.is_file() and sha256_of(dest) == sha256:
        print(f"  {dest.name}: already downloaded, hash OK")
        return
    download(url, dest)
    got = sha256_of(dest)
    if got != sha256:
        dest.unlink(missing_ok=True)
        fail(f"sha256 mismatch for {dest.name}\n  expected {sha256}\n  got      {got}\n  The file was deleted.")
    print(f"  {dest.name}: hash OK")




# ---------------------------------------------------------------------------
# Step 2: conda packages
# ---------------------------------------------------------------------------

def ensure_conda_packages():
    # cuda-nvcc, cuda-cudart-dev and cuda-libraries-dev are the conda-forge split packages
    # for CUDA 12 (compiler, runtime headers and libs, library headers and libs).
    # cuda-version=12.8 stops the solver from picking a newer CUDA. If the solver rejects the
    # split packages, fall back to the cuda-toolkit metapackage, which pulls in the same set.
    pkgs = []
    if shutil.which("git") is None:
        pkgs.append("git")
    need_cuda = not nvcc_is_128()
    if not pkgs and not need_cuda:
        print("  OK, already done")
        return
    split = ["cuda-version=12.8", "cuda-nvcc=12.8", "cuda-cudart-dev=12.8", "cuda-libraries-dev=12.8"]
    ok = conda_install(*pkgs, *(split if need_cuda else []))
    if not ok and need_cuda:
        print("  split packages failed, trying cuda-toolkit=12.8")
        ok = conda_install(*pkgs, "cuda-version=12.8", "cuda-toolkit=12.8")
    if not ok:
        fail("conda install failed (see output above)")
    prepend_path("PATH", [lib_dir() / "bin", lib_dir() / "cmd"])
    if shutil.which("git") is None:
        fail("git is still not on PATH after installing it")
    if not nvcc_is_128():
        fail(f"nvcc 12.8 not found at {lib_dir() / 'bin' / 'nvcc.exe'} after installing")




# ---------------------------------------------------------------------------
# Step 3: MSVC
# ---------------------------------------------------------------------------

def msvc_candidates():
    """Portable MSVC setup_x64.bat files to reuse, in order of preference."""
    return [
        TOOLS_DIR / "msvc" / "setup_x64.bat",
        EXP_DIR.parent / "HY-World-Experimentation" / "tools" / "msvc" / "setup_x64.bat",
        Path(r"D:\hyw\HY-World-Experimentation\tools\msvc\setup_x64.bat"),
    ]


def find_installed_vcvars():
    """vcvars64.bat of an installed Visual Studio (found through vswhere), else None."""
    pf86 = os.environ.get("ProgramFiles(x86)")
    if not pf86:
        return None
    vswhere = Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    r = subprocess.run(
        [str(vswhere), "-latest", "-products", "*",
         "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"],
        capture_output=True, text=True,
    )
    lines = r.stdout.strip().splitlines()
    if r.returncode == 0 and lines:
        bat = Path(lines[0].strip()) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if bat.exists():
            return bat
    return None


def find_vcvars(candidates=None, installed=None):
    """An installed Visual Studio first, then the first existing portable MSVC, else None."""
    found = installed if installed is not None else find_installed_vcvars()
    if found:
        return Path(found)
    for bat in (candidates if candidates is not None else msvc_candidates()):
        if Path(bat).exists():
            return Path(bat)
    return None


def parse_set_output(text):
    """Parse the output of the cmd 'set' command into a dict."""
    env = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep or not key or key.startswith("="):
            continue
        env[key] = value
    return env


def load_env_from_bat(bat):
    """Run a .bat in cmd and copy the environment it leaves behind into this process."""
    # The whole string is passed as is. /s makes cmd strip the outer quotes only.
    cmd = f'cmd /s /c "call "{bat}" >nul && set"'
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        fail(f"{bat} failed (exit {r.returncode}):\n{r.stdout}{r.stderr}")
    env = parse_set_output(r.stdout)
    if not any(k.upper() == "PATH" for k in env):
        fail(f"could not read the environment after running {bat}")
    os.environ.update(env)
    return env


def check_cl():
    cl = shutil.which("cl")
    if not cl:
        fail("cl.exe is not on PATH after loading the MSVC environment")
    r = subprocess.run([cl], capture_output=True, text=True, errors="replace")
    m = re.search(r"Version (\d+)\.(\d+)\.(\d+)", r.stdout + r.stderr)
    if not m:
        fail(f"could not read the cl version from: {cl}")
    major, minor = int(m.group(1)), int(m.group(2))
    print(f"  cl {m.group(1)}.{m.group(2)}.{m.group(3)} (MSVC toolset 14.{minor}) at {cl}")
    if (major, minor) >= (19, 50):
        print("  WARNING: CUDA 12.8 supports MSVC toolsets up to 14.44. This cl is newer,")
        print("  so nvcc builds may fail. Use portable-msvc.py with --msvc-version 14.44.")


def install_portable_msvc():
    """Download the pinned portable-msvc.py, check its hash, run it. Returns the setup bat."""
    print("  No Visual Studio C++ tools found. Setting up a portable MSVC, no admin needed.")
    TOOLS_DIR.mkdir(exist_ok=True)
    download_verified(MSVC_SCRIPT_URL, MSVC_SCRIPT_PATH, MSVC_SCRIPT_SHA256)
    base = [sys.executable, str(MSVC_SCRIPT_PATH), "--vs", "2022"]
    print()
    print("  The next step downloads MSVC from Microsoft. The script asks you to read and")
    print("  accept the Microsoft Visual Studio license. Answer in this window (Y or N).")
    print()
    # No stdin or stdout redirection and no --accept-license on purpose: the user answers.
    r = subprocess.run([*base, "--msvc-version", MSVC_VERSION], cwd=TOOLS_DIR)
    if r.returncode != 0 or not PORTABLE_MSVC_BAT.exists():
        print()
        print(f"  portable-msvc.py did not finish (exit {r.returncode}). Versions it offers:")
        subprocess.run([*base, "--show-versions"], cwd=TOOLS_DIR)
        fail(
            f"could not set up MSVC {MSVC_VERSION}. If you declined the license, run again and accept it.\n"
            "  If the version is not offered, edit MSVC_VERSION in setup_env.py to the highest 14.4x listed above."
        )
    shutil.rmtree(TOOLS_DIR / "downloads", ignore_errors=True)
    return PORTABLE_MSVC_BAT


def set_build_env():
    lib = lib_dir()
    os.environ.update(
        CUDA_HOME=str(lib),
        CUDA_PATH=str(lib),
        DISTUTILS_USE_SDK="1",
        MSSdk="1",
        TORCH_CUDA_ARCH_LIST="12.0",
        FORCE_CUDA="1",
    )
    # setup.py skips the CUDA kernels when BUILD_NO_CUDA=1. The build here needs them.
    os.environ.pop("BUILD_NO_CUDA", None)
    prepend_path("PATH", [lib / "bin", lib / "cmd"])
    # conda-forge puts the CUDA headers in Library\include and the .lib files in Library\lib.
    # torch only adds CUDA_HOME\lib\x64 to the linker, so add both through INCLUDE and LIB.
    # The CCCL headers (cuda/std/..., nv/target) sit in Library\include\targets\x64 on
    # conda-forge for Windows. nvcc finds them through its own profile, but cl, which compiles
    # the .cpp files, only sees INCLUDE. CUDA 13 moves them one level down into cccl.
    prepend_path("INCLUDE", [lib / "include",
                             lib / "include" / "targets" / "x64",
                             lib / "include" / "targets" / "x64" / "cccl"])
    prepend_path("LIB", [lib / "lib", lib / "lib" / "x64"])




# ---------------------------------------------------------------------------
# Step 4: torch
# ---------------------------------------------------------------------------

def torch_is_expected():
    code = (
        "import sys, torch, torchvision\n"
        f"ok = torch.__version__.startswith('{TORCH_VERSION}') and torch.version.cuda == '12.8'\n"
        f"ok = ok and torchvision.__version__.startswith('{TORCHVISION_VERSION}')\n"
        "print(torch.__version__, 'cuda', torch.version.cuda, 'torchvision', torchvision.__version__)\n"
        "sys.exit(0 if ok else 1)\n"
    )
    r = run_py(code)
    if r.stdout.strip():
        print("  found:", r.stdout.strip())
    return r.returncode == 0


def install_torch(force=False):
    flags = ["--force-reinstall", "--no-deps"] if force else []
    pip("install", *flags, f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}",
        "--index-url", CU128_INDEX)
    if not torch_is_expected():
        fail(f"torch is still not the {TORCH_VERSION} CUDA 12.8 build after installing")


def ensure_torch():
    if torch_is_expected():
        print("  OK, already done")
        return
    print("  installing the torch cu128 build")
    install_torch()


def require_cuda_and_arch(cwd=None):
    code = (
        "import sys, torch\n"
        "print('torch', torch.__version__, 'cuda', torch.version.cuda)\n"
        "arch = torch.cuda.get_arch_list()\n"
        "print('arch list:', ' '.join(arch))\n"
        "avail = torch.cuda.is_available()\n"
        "print('torch.cuda.is_available():', avail)\n"
        "if 'sm_120' not in arch:\n"
        "    print('sm_120 (RTX 50 series) is missing from this torch build')\n"
        "    sys.exit(2)\n"
        "if not avail:\n"
        "    sys.exit(1)\n"
        "p = torch.cuda.get_device_properties(0)\n"
        "print('GPU:', p.name, '|', round(p.total_memory / 1024**3, 1), 'GB VRAM')\n"
    )
    r = run_py(code, cwd=cwd, capture=False)
    if r.returncode == 2:
        fail("this torch build has no sm_120 kernels (see output above)")
    if r.returncode != 0:
        fail("CUDA is not available to torch (see output above)")




# ---------------------------------------------------------------------------
# Step 5: clone
# ---------------------------------------------------------------------------

def git_run(repo, *args):
    # Stop git from looking above the repo, so a repository around this folder
    # cannot make git apply skip files or rev-parse answer for the wrong repo.
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=Path(repo).parent.as_posix())
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, errors="replace"
    )


def git_show(cwd, *args):
    """Run git with its output on the console (network steps). Returns the exit code."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    cmd = ["git", *args]
    print("  >", " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, env=env).returncode


def git_head(repo):
    r = git_run(repo, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def clone_version(v):
    dest = EXP_DIR / v["folder"]
    sha = v["sha"]
    if shutil.which("git") is None:
        fail("git not found on PATH (step 2 should have installed it)")
    if dest.exists():
        if not (dest / ".git").exists():
            fail(f"{dest} exists but is not a git clone. Remove or rename it and run again.")
        head = git_head(dest)
        if head == sha:
            print(f"  OK, {dest.name} is already at {sha[:7]}")
        else:
            dirty = git_run(dest, "status", "--porcelain").stdout.strip()
            if dirty:
                fail(f"{dest} is at {head} with local changes, expected {sha}. Remove or rename it and run again.")
            print(f"  {dest.name} is at {str(head)[:7]}, checking out {sha[:7]}")
            if git_show(dest, "checkout", sha) != 0:
                fail(f"git checkout {sha} failed in {dest}")
    else:
        # core.autocrlf=false keeps LF line endings, so Windows patches apply the same on any PC.
        rc = git_show(EXP_DIR, "clone", "-c", "core.autocrlf=false", "-c", "core.longpaths=true",
                      "--recursive", GSPLAT_URL, str(dest))
        if rc != 0:
            fail(f"git clone failed (see output above). Remove {dest} if it was left behind.")
        if git_show(dest, "checkout", sha) != 0:
            fail(f"git checkout {sha} failed in {dest}")
    if git_head(dest) != sha:
        fail(f"{dest} is not at {sha} after checkout")
    if not (dest / GLM_HEADER_REL).exists():
        if git_show(dest, "submodule", "update", "--init", "--recursive") != 0:
            fail("git submodule update failed (see output above)")
    elif dest.exists():
        print("  submodules present")
    if not (dest / GLM_HEADER_REL).exists():
        fail(f"{dest / GLM_HEADER_REL} is missing after the submodule update (glm submodule)")
    print(f"  glm headers OK, {dest.name} at {sha[:7]}")
    return dest




# ---------------------------------------------------------------------------
# Step 6: optional Windows patch
# ---------------------------------------------------------------------------

def find_patch(key, patch_dir=None):
    """patches/gsplat-<version>_windows.patch (1.5.3 style name first, then 153 style), or None."""
    patch_dir = Path(patch_dir or PATCH_DIR)
    v = VERSIONS[key]
    for name in (f"gsplat-{v['label']}_windows.patch", f"gsplat-{key}_windows.patch"):
        if (patch_dir / name).is_file():
            return patch_dir / name
    return None


def patch_target_files(patch_text):
    """Paths from the '+++ b/...' lines of a unified diff."""
    files = []
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip()
            if path == "/dev/null":
                continue
            if path.startswith("b/"):
                path = path[2:]
            files.append(path)
    return files


def files_missing_marker(repo, files):
    missing = []
    for rel in files:
        path = Path(repo) / rel
        if not path.is_file() or PATCH_MARKER not in read_text(path):
            missing.append(rel)
    return missing


def apply_gsplat_patch(repo, patch_path):
    patch_path = Path(patch_path)
    if not patch_path.is_file():
        fail(f"patch file missing: {patch_path}")
    files = patch_target_files(read_text(patch_path))
    if not files:
        fail(f"no '+++ b/...' lines found in {patch_path}")
    # A checkout with core.autocrlf=true turns the patch into CRLF, which no longer matches
    # the LF files of the clone. Apply an LF copy instead.
    TOOLS_DIR.mkdir(exist_ok=True)
    lf_copy = TOOLS_DIR / f"{patch_path.stem}.lf.patch"
    lf_copy.write_bytes(patch_path.read_bytes().replace(b"\r\n", b"\n"))
    patch = str(lf_copy)
    if git_run(repo, "apply", "--check", "-R", patch).returncode == 0 \
            and not files_missing_marker(repo, files):
        print("  OK, already done")
        return
    r = git_run(repo, "apply", "--check", patch)
    if r.returncode != 0:
        fail(f"the patch does not apply to {repo} (upstream changed, or half applied):\n{r.stderr}")
    r = git_run(repo, "apply", patch)
    if r.returncode != 0:
        fail(f"git apply failed:\n{r.stderr}")
    missing = files_missing_marker(repo, files)
    if missing:
        fail(
            f"git apply ran but '{PATCH_MARKER}' is missing in: {', '.join(missing)}\n"
            "  git may have skipped files because the folder is inside another git repository."
        )
    print(f"  applied {patch_path.name} to {len(files)} file(s)")


def apply_optional_patch(key, repo, patch_dir=None):
    """Apply the version's Windows patch if its file exists. Returns the patch path or None."""
    patch = find_patch(key, patch_dir)
    if patch is None:
        print("  no Windows patch for this version")
        others = sorted(Path(patch_dir or PATCH_DIR).glob("*.patch")) if Path(patch_dir or PATCH_DIR).is_dir() else []
        if others:
            print("  (other patch files in patches: " + ", ".join(p.name for p in others) + ")")
        return None
    apply_gsplat_patch(repo, patch)
    return patch




# ---------------------------------------------------------------------------
# Step 7: build gsplat
# ---------------------------------------------------------------------------

def kernels_built(repo):
    """True when gsplat/csrc*.pyd exists in the clone and the env imports gsplat from there.
    Does not import gsplat, which could start a JIT build."""
    repo = Path(repo)
    found = glob.glob(str(repo / "gsplat" / "csrc*.pyd")) + glob.glob(str(repo / "gsplat" / "csrc*.so"))
    if not found:
        return False
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.find_spec('gsplat')\n"
        "if spec is None or not spec.submodule_search_locations:\n"
        "    sys.exit(1)\n"
        "print(list(spec.submodule_search_locations)[0])\n"
    )
    r = run_py(code, cwd=sys.prefix)
    if r.returncode != 0:
        return False
    return Path(r.stdout.strip()).resolve().is_relative_to(repo.resolve())


def build_gsplat(v, repo):
    set_build_env()
    for var in ("CUDA_HOME", "CUDA_PATH", "DISTUTILS_USE_SDK", "MSSdk", "TORCH_CUDA_ARCH_LIST"):
        print(f"  {var}={os.environ[var]}")
    print(f"  BUILD_NO_CUDA={os.environ.get('BUILD_NO_CUDA', '(not set)')}")
    if not (lib_dir() / "include" / "cuda_runtime.h").exists():
        print(f"  WARNING: {lib_dir() / 'include' / 'cuda_runtime.h'} not found, CUDA builds will fail")
    if kernels_built(repo):
        print("  OK, already done")
        return
    # Build tools first. --no-build-isolation (below) makes pip use these instead of an
    # empty temporary env, so they must be in this env.
    print("  installing the build tools setup.py needs")
    pip_or_fail("install", "setuptools>=64", "wheel", "ninja", "rich", v["numpy"])
    print("  NOTE: this compiles the gsplat CUDA kernels. It takes a long time (often 10 to 30")
    print("  minutes) and the window can look stuck. Let it run.")
    # --no-build-isolation is required on both versions. setup.py imports torch to build the
    # CUDA extension. 1.5.3 has no pyproject.toml, so pip would build in an empty isolated env
    # without torch. 1.6.0 lists "torch>=2.7" as a build requirement, and an isolated env would
    # download a different torch (the Windows PyPI wheel is CPU only) instead of our cu128 one.
    args = ["install", "-e", ".", "--no-build-isolation", "-v"]
    rc, text = pip_capture(*args, cwd=repo, env=dict(os.environ))
    if rc != 0:
        log = save_failure_log(f"{repo.name}_build", text)
    if rc != 0 and v["experimental"] and "experimental" in text.lower():
        print()
        print("  The build failed inside gsplat/experimental. 1.6.0 builds that second extension")
        print("  by default (BUILD_EXPERIMENTAL=1), but simple_trainer.py does not use it.")
        print("  SKIPPED (not used by simple_trainer on COLMAP): gsplat.experimental.render.kernels.csrc")
        print("  Retrying with BUILD_EXPERIMENTAL=0.")
        rc, text = pip_capture(*args, cwd=repo, env=dict(os.environ, BUILD_EXPERIMENTAL="0"))
        if rc != 0:
            log = save_failure_log(f"{repo.name}_build_no_experimental", text)
    if rc != 0:
        fail(f"pip install -e . failed. Send the error lines above, or the whole file {log}")
    if not kernels_built(repo):
        fail("gsplat was installed but no compiled gsplat/csrc module was found in the clone")




# ---------------------------------------------------------------------------
# Step 8: examples requirements
# ---------------------------------------------------------------------------

def req_name(line):
    """Normalized project name of a requirements line, or None for comments and blanks."""
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("-"):
        return None
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(@|[<>=!~;]|$)", s)
    if m and not s.startswith("git+"):
        return m.group(1).lower().replace("_", "-").replace(".", "-")
    m = re.match(r"^git\+\S*?/([A-Za-z0-9._-]+?)(\.git)?(@\S*)?$", s)
    if m:
        return m.group(1).lower().replace("_", "-").replace(".", "-")
    return None


def filter_requirements(text, names):
    """Drop requirement lines whose project name is in names. Returns (new text, dropped lines)."""
    keep, dropped = [], []
    for line in text.splitlines(keepends=True):
        if req_name(line) in names:
            dropped.append(line.strip())
        else:
            keep.append(line)
    return "".join(keep), dropped


def failure_mentions(text, name):
    t = text.lower().replace("_", "-")
    return name in t


def install_examples_requirements(req_path):
    """pip install -r on the file, as is. Returns True when pip ran."""
    marker = Path(sys.prefix) / "gsplat_examples_requirements.sha256"
    digest = sha256_of(req_path)
    if marker.exists() and marker.read_text().strip() == digest:
        print("  OK, already done")
        return False
    print("  NOTE: several entries are git+ packages that compile CUDA code (fused-ssim, fused-bilagrid).")
    print("  This takes a while and the window can look stuck. Let it run.")
    base = ["install", "--no-build-isolation", "--progress-bar", "off"]
    rc, text = pip_capture(*base, "-r", str(req_path), env=dict(os.environ))
    if rc != 0:
        save_failure_log(f"{Path(req_path).parents[1].name}_examples_requirements", text)
        print()
        print("  pip failed on the requirements file. Last lines of its output:")
        for line in text.strip().splitlines()[-12:]:
            print("   |", line)
        names = {n for n in OPTIONAL_REQS if failure_mentions(text, n)}
        present = {req_name(l) for l in read_text(req_path).splitlines()}
        names &= present
        if not names:
            fail("pip install -r failed on an entry this setup does not treat as optional (see output above).")
        tmp_req = Path(sys.prefix) / "gsplat_examples_requirements_filtered.txt"
        new_text, dropped = filter_requirements(read_text(req_path), names)
        write_text(tmp_req, new_text)
        for line in dropped:
            print(f"  SKIPPED (not used by simple_trainer on COLMAP): {line}  [{OPTIONAL_REQS[req_name(line)]}]")
        rc, text = pip_capture(*base, "-r", str(tmp_req), env=dict(os.environ))
        tmp_req.unlink(missing_ok=True)
        if rc != 0:
            log = save_failure_log(f"{Path(req_path).parents[1].name}_examples_requirements_filtered", text)
            fail(f"pip install -r failed again even without the skipped entries. Send the error lines above, or {log}")
    marker.write_text(digest + "\n")
    return True




# ---------------------------------------------------------------------------
# Step 9: verify
# ---------------------------------------------------------------------------

SMOKE_CODE = """
import torch
from gsplat import rasterization
dev = 'cuda'
torch.manual_seed(0)
N = 1000
means = torch.randn(N, 3, device=dev) * 0.5
means[:, 2] += 2.0
means.requires_grad_(True)
quats = torch.randn(N, 4, device=dev)
quats = quats / quats.norm(dim=-1, keepdim=True)
scales = torch.full((N, 3), 0.05, device=dev)
opacities = torch.full((N,), 0.8, device=dev)
colors = torch.rand(N, 3, device=dev)
viewmats = torch.eye(4, device=dev)[None]
Ks = torch.tensor([[100.0, 0, 50], [0, 100.0, 50], [0, 0, 1.0]], device=dev)[None]
render, alpha, info = rasterization(
    means, quats, scales, opacities, colors, viewmats, Ks, 100, 100, packed=False
)
assert torch.isfinite(render).all(), 'render has non finite values'
r = info['radii']
visible = int((r > 0).any(dim=-1).sum()) if r.dim() >= 3 else int((r > 0).sum())
assert visible > 0, 'no visible gaussians'
assert float(alpha.sum()) > 0, 'alpha is zero'
render.sum().backward()
g = means.grad
assert g is not None and torch.isfinite(g).all(), 'means grad missing or non finite'
assert float(g.abs().sum()) > 0, 'means grad is zero'
print('visible', visible, 'alpha mean', float(alpha.mean()), 'grad abs sum', float(g.abs().sum()))
"""


def verify_checks(key):
    pycolmap_code = "import pycolmap\nprint(getattr(pycolmap, '__version__', 'ok'))"
    if key == "153":
        pycolmap_code = "import pycolmap\nfrom pycolmap import SceneManager\nprint('SceneManager ok')"
    return [
        ("gsplat compiled module", "import torch\nimport gsplat.csrc as c\nprint(c.__file__)", None),
        ("rasterization forward and backward on CUDA", SMOKE_CODE, None),
        ("fused_ssim", "import torch, fused_ssim\nprint(fused_ssim.__file__)", None),
        ("pycolmap", pycolmap_code, None),
        ("examples datasets.colmap Parser", "from datasets.colmap import Parser\nprint('Parser ok')", "examples"),
    ]


def run_checks(key, repo):
    failed = []
    for label, code, sub in verify_checks(key):
        cwd = (repo / sub) if sub else sys.prefix
        r = run_py(code, cwd=cwd)
        if r.returncode == 0:
            detail = r.stdout.strip().splitlines()[-1:]
            print(f"  OK      {label}" + (f"  ({detail[0]})" if detail else ""))
        else:
            failed.append(label)
            tail = (r.stderr or r.stdout).strip().splitlines()[-4:]
            print(f"  FAILED  {label}")
            for line in tail:
                print(f"          {line}")
    return failed




# ---------------------------------------------------------------------------
# One version, start to finish
# ---------------------------------------------------------------------------

def setup_version(key):
    v = VERSIONS[key]
    total = TOTAL_STEPS
    if os.name != "nt":
        fail("this setup is for Windows only")
    os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    prepend_path("PATH", [lib_dir() / "bin", lib_dir() / "cmd"])
    TOOLS_DIR.mkdir(exist_ok=True)

    step(2, total, "conda packages: git and the CUDA 12.8 toolchain (conda-forge)")
    ensure_conda_packages()

    step(3, total, "MSVC (C++ compiler for the CUDA builds)")
    bat = find_vcvars()
    if bat is None:
        bat = install_portable_msvc()
    print(f"  using {bat}")
    load_env_from_bat(bat)
    check_cl()
    write_text(MSVC_ENV_FILE, str(bat) + "\n")

    step(4, total, f"torch {TORCH_VERSION} + torchvision {TORCHVISION_VERSION}, CUDA 12.8 build")
    # Both versions use the same torch so the comparison is fair. 1.6.0's
    # examples/requirements.txt pins exactly these and says torch MUST be pre-installed.
    ensure_torch()
    require_cuda_and_arch()

    step(5, total, f"Clone gsplat {v['label']} (commit {v['sha'][:7]})")
    repo = clone_version(v)

    step(6, total, "Windows patch (only if patches\\ has one for this version)")
    apply_optional_patch(key, repo)

    step(7, total, f"Build gsplat {v['label']} (pip install -e ., CUDA compiled at install)")
    build_gsplat(v, repo)

    step(8, total, "examples/requirements.txt (pip install -r, no build isolation)")
    req_path = repo / "examples" / "requirements.txt"
    if not req_path.exists():
        fail(f"{req_path} not found (upstream changed?)")
    pip_ran = install_examples_requirements(req_path)
    if not pip_ran:
        print("  torch check skipped, nothing was installed")
    elif torch_is_expected():
        print("  OK, torch is still the cu128 build")
    else:
        print("  torch was swapped by pip, reinstalling the cu128 build")
        install_torch(force=True)

    step(9, total, "Verify")
    failed = run_checks(key, repo)
    if failed:
        fail("verification failed for: " + ", ".join(failed))
    print(f"GSPLAT {v['label']} ENV OK")




# ---------------------------------------------------------------------------
# Summary (run with the env's python, imports neither torch nor gsplat)
# ---------------------------------------------------------------------------

def summary(key):
    import importlib.metadata as md
    v = VERSIONS[key]
    repo = EXP_DIR / v["folder"]

    def ver(name):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return "not installed"

    head = git_head(repo) if (repo / ".git").exists() else None
    patch = find_patch(key)
    print(f"  gsplat {v['label']}  env {v['env']}")
    print(f"    clone:    {repo}" + (f"  at {head[:7]}" if head else "  (missing)"))
    print(f"    gsplat:   {ver('gsplat')}   torch: {ver('torch')}   torchvision: {ver('torchvision')}")
    print(f"    kernels:  {'built' if kernels_built(repo) else 'NOT built'}")
    print(f"    patch:    {patch.name if patch else 'none for this version'}")
    print(f"    run in:   {repo / 'examples'}")




# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Set up one gsplat version in the active conda env.")
    parser.add_argument("mode", choices=[*VERSIONS, "summary"])
    parser.add_argument("version", nargs="?", choices=list(VERSIONS))
    args = parser.parse_args()

    if args.mode == "summary":
        if not args.version:
            parser.error("summary needs a version (153 or 160)")
        summary(args.version)
        return

    print(f"Python {sys.version.split()[0]} in {sys.prefix}")
    print(f"gsplat {VERSIONS[args.mode]['label']} into env {VERSIONS[args.mode]['env']}")
    setup_version(args.mode)
    print()
    print("Setup finished.")


if __name__ == "__main__":
    main()
