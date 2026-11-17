"""Run gsplat's official trainer with a GPU memory cap and a crash-safe GPU log.

Two protections are added around the trainer, and no gsplat code is changed:

1. PyTorch is capped at a fraction of the GPU memory. A run that needs more
   stops with a clean out of memory error instead of the NVIDIA driver moving
   memory into system RAM, which can freeze or restart the PC.
2. The GPU is logged with nvidia-smi every few seconds to a CSV file that is
   flushed and fsynced after every line, so a crash leaves the last readings.

Usage:
    python guarded_train.py <gpu_log_csv> <trainer_script> [trainer args...]

Example:
    python guarded_train.py results\\gpu_log.csv simple_trainer.py default --data_dir data\\stump

This script only wraps the official trainer (examples/simple_trainer.py). The
trainer runs in the same process through runpy, with its arguments unchanged.

Exit codes: 0 or the trainer's own code on normal exit, 1 on bad usage or no
CUDA device, 2 when the run was stopped by the memory cap.
"""

import os
import runpy
import subprocess
import sys
import threading
from typing import List, Optional

import torch




# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEMORY_FRACTION = 0.90
CUDA_DEVICE = 0
GPU_LOG_INTERVAL_S = 2
NVIDIA_SMI_FIELDS = (
    "timestamp,memory.used,memory.total,temperature.gpu,"
    "power.draw,utilization.gpu,clocks.sm"
)
NVIDIA_SMI_TIMEOUT_S = 10
LOGGER_JOIN_TIMEOUT_S = 15
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_OUT_OF_MEMORY = 2
BYTES_PER_GIB = 1024 ** 3
USAGE = "Usage: python guarded_train.py <gpu_log_csv> <trainer_script> [trainer args...]"
OOM_TEXT = "out of memory"




# ---------------------------------------------------------------------------
# GPU logger
# ---------------------------------------------------------------------------

class GpuLogger:
    """Background thread that appends nvidia-smi readings to a CSV file.

    Every line is flushed and fsynced so the last readings survive a crash.
    If nvidia-smi is missing or fails, one warning is printed and logging
    stops, while the training carries on.
    """

    def __init__(self, log_path: str) -> None:
        """Prepare the logger without starting the thread.

        Args:
            log_path: CSV file to append to. Parent folders are created.

        Returns:
            None
        """
        self.log_path = log_path
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gpu-logger", daemon=True)
        self._failed = False
        self._lock = threading.Lock()
        self._file = None




    def start(self) -> None:
        """Open the CSV, write the header if needed and start the thread.

        Args:
            None

        Returns:
            None
        """
        try:
            folder = os.path.dirname(os.path.abspath(self.log_path))
            os.makedirs(folder, exist_ok=True)
            needs_header = (
                not os.path.exists(self.log_path)
                or os.path.getsize(self.log_path) == 0
            )
            self._file = open(self.log_path, "a", encoding="utf-8")
            if needs_header:
                self._write_line(NVIDIA_SMI_FIELDS)
        except OSError as error:
            self._failed = True
            print(f"warning: GPU logging disabled, cannot open {self.log_path}: {error}")
            return
        self._thread.start()




    def stop(self) -> None:
        """Write one last reading, stop the thread and close the file.

        Args:
            None

        Returns:
            None
        """
        if self._file is None:
            return
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=LOGGER_JOIN_TIMEOUT_S)
        self._take_reading()
        with self._lock:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None




    def _run(self) -> None:
        """Thread body: read immediately, then once per interval until stopped.

        Args:
            None

        Returns:
            None
        """
        while not self._failed:
            self._take_reading()
            if self._stop_event.wait(GPU_LOG_INTERVAL_S):
                break




    def _take_reading(self) -> None:
        """Run nvidia-smi once and append its line to the CSV.

        On any failure, print one warning and stop logging for good.

        Args:
            None

        Returns:
            None
        """
        if self._failed:
            return
        command = [
            "nvidia-smi",
            f"--query-gpu={NVIDIA_SMI_FIELDS}",
            "--format=csv,noheader,nounits",
            "-i",
            str(CUDA_DEVICE),
        ]
        extra = {}
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", None)
        if no_window is not None:
            extra["creationflags"] = no_window
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=NVIDIA_SMI_TIMEOUT_S,
                **extra,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or f"exit code {result.returncode}")
            line = result.stdout.strip()
            if not line:
                raise RuntimeError("empty output")
            self._write_line(line)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            self._failed = True
            print(f"warning: GPU logging stopped, nvidia-smi failed: {error}")




    def _write_line(self, line: str) -> None:
        """Append one line to the CSV, then flush and fsync it.

        Args:
            line: Text to write, without a trailing newline.

        Returns:
            None
        """
        with self._lock:
            if self._file is None:
                return
            self._file.write(line + "\n")
            self._file.flush()
            os.fsync(self._file.fileno())




# ---------------------------------------------------------------------------
# Memory cap and trainer
# ---------------------------------------------------------------------------

def apply_memory_cap() -> Optional[float]:
    """Cap PyTorch at MEMORY_FRACTION of the GPU memory.

    Args:
        None

    Returns:
        The cap in GiB, or None when no CUDA device is available.
    """
    if not torch.cuda.is_available():
        print("error: no CUDA device available to PyTorch, so the memory cap cannot be set")
        return None
    torch.cuda.set_per_process_memory_fraction(MEMORY_FRACTION, CUDA_DEVICE)
    total = torch.cuda.get_device_properties(CUDA_DEVICE).total_memory
    cap_gib = total * MEMORY_FRACTION / BYTES_PER_GIB
    print(
        f"memory cap: {MEMORY_FRACTION:.0%} of {total / BYTES_PER_GIB:.2f} GiB "
        f"= {cap_gib:.2f} GiB (PyTorch stops with out of memory above this)"
    )
    return cap_gib




def is_out_of_memory(error: BaseException) -> bool:
    """Tell whether an exception is a CUDA out of memory error.

    Args:
        error: The exception raised by the trainer.

    Returns:
        True for torch's OutOfMemoryError or a RuntimeError saying out of memory.
    """
    oom_class = getattr(torch, "OutOfMemoryError", None) or getattr(
        torch.cuda, "OutOfMemoryError", None
    )
    if oom_class is not None and isinstance(error, oom_class):
        return True
    return isinstance(error, RuntimeError) and OOM_TEXT in str(error).lower()




def run_trainer(script: str, args: List[str]) -> None:
    """Run the trainer script in this process as if it were started directly.

    Args:
        script: Path to the trainer script, for example simple_trainer.py.
        args: Command line arguments for the trainer, passed unchanged.

    Returns:
        None
    """
    script = os.path.abspath(script)
    sys.argv = [script] + list(args)
    sys.path.insert(0, os.path.dirname(script))
    runpy.run_path(script, run_name="__main__")




def main() -> int:
    """Entry point: set the cap, start the GPU log, run the trainer.

    Args:
        None

    Returns:
        The process exit code.
    """
    argv = sys.argv[1:]
    if len(argv) < 2:
        print(USAGE)
        return EXIT_USAGE
    log_path, script, trainer_args = argv[0], argv[1], argv[2:]

    cap_gib = apply_memory_cap()
    if cap_gib is None:
        return EXIT_USAGE
    print(f"GPU log: {os.path.abspath(log_path)} (every {GPU_LOG_INTERVAL_S} s)")

    logger = GpuLogger(log_path)
    logger.start()
    try:
        run_trainer(script, trainer_args)
    except SystemExit:
        raise
    except BaseException as error:
        if is_out_of_memory(error):
            print()
            print("=" * 72)
            print(
                f"Stopped: the run needed more than the {MEMORY_FRACTION:.0%} GPU memory "
                f"cap ({cap_gib:.2f} GiB)."
            )
            print(
                "The PC was protected from the driver moving memory into system RAM."
            )
            print("Try the mcmc option, which caps the Gaussians.")
            print(f"Original error: {str(error).splitlines()[0] if str(error) else error!r}")
            print("=" * 72)
            return EXIT_OUT_OF_MEMORY
        raise
    finally:
        logger.stop()
    return EXIT_OK




if __name__ == "__main__":
    sys.exit(main())
