# gsplat Experiment

Builds the official nerfstudio gsplat on the Windows lab PC (RTX 5070, no admin rights) inside conda, and compares two versions on the Mip-NeRF 360 stump scene with gsplat's own trainer. This is the fallback track for the Terrestrial pipeline (RealityScan, gsplat, SOG), before fixing our own gsplat trainer.

This document covers:

* Setting up the lab PC with one click
* Running the stump benchmark for both versions
* Comparing the results
* Running the Amorphophallus 360 from the frontend
* Checking stump's camera coverage with RealityScan
* What to do when the PC crashes during training
* Findings so far
* Deviations from the official gsplat docs



## Related

* Official repo: https://github.com/nerfstudio-project/gsplat
* Windows install docs: `gsplat-1.6.0/docs/INSTALL_WIN.md`
* Benchmark script: `gsplat-1.6.0/examples/benchmarks/basic.sh`
* Our trainer (in the Taletoreum repo): `src/terrestrial_decolonization/pipeline/train.py`



## Versions

* `153`: gsplat v1.5.3, the latest tagged release and the version Taletoreum uses. Commit 937e299, clone `gsplat-1.5.3`, env `gsplat153`
* `160`: gsplat main, which calls itself 1.6.0 but is not released yet. Pinned at commit 512d366 (2026-09-19), clone `gsplat-1.6.0`, env `gsplat160`

Both use torch 2.9.1 cu128, the version main's examples require, so the comparison is fair.



## Setup

1. Copy this whole folder to the lab PC, to a short path with no spaces, for example `D:\hyw\gsplat-experiment`
2. Double click `setup.bat`. It sets up both versions. `setup.bat 153` or `setup.bat 160` sets up one
3. If no Visual Studio or portable MSVC is found, it downloads Microsoft's build tools and asks you to accept the Microsoft license in the window. It reuses `HY-World-Experimentation\tools\msvc` when that folder sits next to this one
4. The setup ends with a check per version (compiled gsplat, a small render test on the GPU, fused-ssim, pycolmap, the COLMAP parser) and opens a ready prompt


### Notes

* The first run compiles gsplat and fused-ssim and takes a long time
* Run `setup.bat` again after a reboot. It only installs what is missing



## Running stump

Run the versions one after the other, never at the same time:

```bat
run_stump.bat 153 7k
```

```bat
run_stump.bat 160 7k
```

Then compare:

```bat
python compare.py
```

Run the full 30,000 step benchmark for the more promising version, for example:

```bat
run_stump.bat 160 30k
```


### Notes

* Each run trains with the official `basic.sh` stump command (`--data_factor 4 --disable_viewer --render_traj_path ellipse`), then evaluates every saved checkpoint. `7k` only adds `--max_steps 7000 --save_steps 7000`
* Results go to `results\<version>\<7k|30k>\stump`, with metrics in `stats\`, renders in `renders\` and the splat in `ply\point_cloud_<step>.ply`
* Every run ends with a summary: the number of Gaussians in each saved splat, read from the `.ply` itself, then PSNR, SSIM, LPIPS, training time and peak GPU memory at each saved step. To show it again for an earlier run: `python compare.py --run results\153\7k\stump`
* If a 30k run crashes the PC, see Crashes during training for the lighter `mcmc` and `packed` runs
* `run_stump.bat` adds the trainer's own `--save_ply` flag to the official command, which only writes the `.ply` files and leaves training unchanged. Open them in SuperSplat (https://superspl.at/editor) to check the quality
* Runs made before `--save_ply` was added have no `.ply`. Export one from the checkpoint with gsplat's own `export_splats`, the same function the flag uses. For 1.5.3 at 7k, from this folder:

```bat
%USERPROFILE%\AppData\Local\miniconda3\envs\gsplat153\python.exe -c "import torch, os; from gsplat import export_splats; c = torch.load(r'results\153\7k\stump\ckpts\ckpt_6999_rank0.pt', map_location='cpu'); s = c['splats']; os.makedirs(r'results\153\7k\stump\ply', exist_ok=True); export_splats(means=s['means'], scales=s['scales'], quats=s['quats'], opacities=s['opacities'], sh0=s['sh0'], shN=s['shN'], format='ply', save_to=r'results\153\7k\stump\ply\point_cloud_6999.ply'); print('saved', len(s['means']), 'Gaussians')"
```
* The first run writes `images_4_png` into the dataset, which gsplat's parser makes because stump's `images_4` files are `.JPG`
* The first evaluation downloads the LPIPS network weights, so it needs internet
* Note per run: time, peak GPU memory, and how the result looks



## Running Amorphophallus

The input is the 360 the frontend serves, `orbit_front_centre.mp4` from the Taletoreum repo (1280x720, 240 frames). All 240 frames are in `data\amorphophallus\frames`. RealityScan finds the camera poses with the same steps as the Taletoreum pipeline, then gsplat trains with the same official command as stump. The scene is called `amorphophallus_rs` and is set up like `stump_rs`: it reads the frames where they are and writes everything into its own `data\amorphophallus_rs` folder.

1. Find the camera poses. This writes `data\amorphophallus_rs\colmap` and ends with how many frames got a pose:

```bat
run_sfm.bat amorphophallus_rs
```

2. Train each version, one after the other:

```bat
run_scene.bat 153 7k amorphophallus_rs
```

```bat
run_scene.bat 160 7k amorphophallus_rs
```

3. Compare with `python compare.py`, which lists each scene separately


### Notes

* RealityScan is looked for in `C:\Program Files\Epic Games\RealityScan`. If it is installed elsewhere, run `set "RS_DIR=<folder>"` in the same window first
* AI masks are on, as in Taletoreum. If few frames get a pose, run again without them: `run_sfm.bat amorphophallus_rs --no-masks --force`
* The first runs wrote into `data\amorphophallus\colmap` and `data\amorphophallus\realityscan`, where the export failed with `err:5618`. Those two folders are not used any more and can be deleted
* The footage is AI generated and covers about 238 degrees, not a full circle. The plant faces the camera in every frame while the background turns, so expect RealityScan to align on the background and the plant to come out smeared
* Training uses `--data_factor 1`, the frames at full size, since they are already 1280x720
* Note the registered frame count from step 1 along with the usual time, memory and look



## Camera coverage with RealityScan

The stump splat has holes, most clearly from above. To see which parts no camera covers, RealityScan aligns stump's own `images_4`, the same 125 images the benchmark trains on, and saves its project. The official trainer then trains on these poses, next to the official COLMAP ones.

1. Align and save the project. This ends with how many images got a pose and names the ones that did not:

```bat
run_sfm.bat stump_rs
```

2. Open `data\stump_rs\realityscan\project.rsproj` in RealityScan. The 3D view shows each camera and the sparse points. Look from above and from the sides for areas with no cameras and no points
3. Train on the RealityScan poses with each version, one after the other:

```bat
run_scene.bat 153 7k stump_rs
```

```bat
run_scene.bat 160 7k stump_rs
```

4. Compare the splats in SuperSplat with the `stump` runs from the same version


### Notes

* An export made before the binary files were added is fixed by running `run_sfm.bat stump_rs` again without `--force`: it checks the existing export and writes the `.bin` files, without running RealityScan again
* `stump_rs` trains with `--data_factor 1` because `images_4` is already a quarter size, so the image size matches the `stump` runs
* The Amorphophallus run saves its project the same way, in `data\amorphophallus_rs\realityscan\project.rsproj`
* A hole that shows up with both COLMAP and RealityScan poses means the cameras never saw that part, not that the poses are wrong



## Crashes during training

A training run that runs out of GPU memory should stop with an error. If the whole PC restarts with a blue screen instead, the fault is below the trainer: the graphics driver, the hardware, or Windows' hypervisor layer. These steps need no admin rights.


### Before a long run

Log the GPU every 5 seconds, so a crash leaves a record of what led up to it. Open a second Command Prompt in this folder and start:

```bat
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,temperature.gpu,power.draw,utilization.gpu --format=csv -l 5 -f gpu_log.csv
```

Then start the run in the first window as usual. Stop the log with Ctrl + C when the run ends.


### After a crash

1. Read the stop code and the time of the last crashes in PowerShell. If it says access denied, lab IT can read it:

```bat
powershell -Command "Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001,41} -MaxEvents 6 | Format-List TimeCreated, Id, Message"
```

2. Check how big the run was at step 7000 in `results\<version>\30k\<scene>\stats\train_step6999_rank0.json`. `mem` is the peak GPU memory in GiB and `num_GS` the number of Gaussians
3. Check the end of `gpu_log.csv` for memory near 12 GB, temperature, and power just before the crash
4. Note the driver version from the top line of `nvidia-smi`


### Lighter runs

`run_scene.bat` (and so `run_stump.bat`) takes two optional words after the scene, in any order. Both come from the official gsplat examples:

* `mcmc`: the official MCMC benchmark (`examples/benchmarks/mcmc.sh`) instead of the default one. It trains with the `mcmc` config and `--strategy.cap-max 1000000`, so there are never more than 1 million Gaussians and memory has a ceiling
* `packed`: the trainer's own `--packed` flag, which uses less GPU memory and runs slightly slower. It works with either config

Try them in this order, until a 30k run finishes:

```bat
run_scene.bat 160 30k stump packed
```

```bat
run_scene.bat 160 30k stump mcmc packed
```

Both options work the same on 1.5.3, which has the same flags. Until 1.6.0 builds, run them with `153`:

```bat
run_scene.bat 153 30k stump packed
```

```bat
run_scene.bat 153 30k stump mcmc packed
```

Each variant gets its own results folder, for example `results\160\30k_mcmc_packed\stump`, and `compare.py` lists it as its own length.


### Notes

* `mcmc` is a different training method from `default`, so its quality is not a like for like comparison with a `default` run. `packed` only changes memory use and speed
* The default trainer adds Gaussians until step 15000, so the halfway point of a 30k run is when memory peaks
* 1.5.3 keeps more Gaussians than intended because of the opacity reset bug under Findings, so it peaks higher than 1.6.0. Run 30k on 160 where possible
* When the 12 GB fills, the NVIDIA driver can move the overflow into system RAM instead of stopping with an error. The run then slows to a crawl and loads the whole system
* If memory stayed well under 12 GB and the crash repeats, it is a lab PC problem. Give lab IT the stop codes, the times, and that each crash happened under sustained full GPU load
* The last lines of `gpu_log.csv` before a crash can be missing



## Findings

* gsplat 1.5.3 never resets opacity: `gsplat/strategy/default.py:195` reads `step % self.reset_every == 0 & step > 0`, which is always false. 1.6.0 fixes it. Taletoreum's trainer uses 1.5.3 `DefaultStrategy`, so it is affected too
* 1.6.0 falls back to a slower SSIM written in plain torch if fused-ssim is missing. The setup checks that fused-ssim is installed for both versions
* A 30k stump run restarted the lab PC about halfway with a blue screen naming the hypervisor. HY-World earlier crashed it with DPC_WATCHDOG_VIOLATION, also under full GPU load. The stop code and the memory at step 7000 are still to be checked with the steps under Crashes during training



## Deviations

* Portable MSVC 14.44 and the conda-forge CUDA 12.8 compiler instead of Visual Studio Build Tools and the CUDA installer, because both installers need admin rights
* git from conda-forge, because the PC has no git
* torch 2.9.1 cu128 from the PyTorch index first, because the Windows PyPI torch is CPU only
* `pip install -e . --no-build-isolation` instead of `pip install -e .`, because an isolated build would compile against a different, CPU-only torch
* 1.6.0 only: if its experimental extension fails to build, the setup retries once without it. `simple_trainer.py` does not use it
* 1.6.0 only: `patches/gsplat-1.6.0_windows.patch` fixes three spots that only compile with Linux's C++ library, each under `#ifdef _MSC_VER` so Linux builds stay upstream: `std::isfinite` in GPU code (`Cameras.cuh`), the GCC built-in `__builtin_clzll` (`RasterizeToPixelsFromWorld3DGSParallelBatchBwd.cu`), and a zero-length `std::array` in GPU code (`SphericalHarmonicsL1PlusCUDA.cu`)
* The conda CUDA headers in `Library\include\targets\x64` are added to `INCLUDE`, because `cl` does not see the folder `nvcc` uses
* `NVCC_APPEND_FLAGS=-DUSE_CUDA=1` while installing `examples/requirements.txt`, so fused-ssim compiles against torch 2.9.1 on Windows. Without it, torch's own `compiled_autograd.h` stops MSVC with "'std': ambiguous symbol" (pytorch/pytorch#148317)
* 1.5.3 only: the pycolmap it pins (rmbrualla/pycolmap) reads COLMAP's 64 bit counts with the struct format `'L'`, which is 8 bytes on Linux but 4 on Windows. The setup changes those formats to `'Q'` in the installed `pycolmap\scene_manager.py`, which gives the same values as on Linux, and its check now reads the stump COLMAP files
* If `examples/requirements.txt` fails on `nvidia-ncore`, `ppisp` or `fused-bilagrid`, that one line is skipped. None of them are used when training on a COLMAP dataset
* `amorphophallus_rs` and `stump_rs` only: camera poses come from RealityScan, as in the Taletoreum pipeline, instead of COLMAP, which the official datasets use
* `amorphophallus_rs` and `stump_rs` only: `run_sfm.bat` also writes RealityScan's text model as `cameras.bin`, `images.bin` and `points3D.bin`, the format the official datasets ship. The pycolmap 1.5.3 pins cannot read COLMAP text on Python 3 ("Input quaternion should be a 3- or 4-vector"). The values are unchanged: on Taletoreum's export, the official pycolmap and the pinned one read the same numbers from the binary files as from the text files
