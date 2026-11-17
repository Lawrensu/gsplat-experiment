# gsplat Experiment

Builds the official nerfstudio gsplat on the Windows lab PC (RTX 5070, no admin rights) inside conda, and trains three scenes with gsplat's own trainer. This is the fallback track for the Terrestrial pipeline (RealityScan, gsplat, SOG), before fixing our own gsplat trainer.

This document covers:

* The order to run everything in
* Setting up the lab PC
* The scenes and the commands
* Camera poses with RealityScan
* Training at 7k and 30k steps
* Reviewing the results
* What to do when the PC crashes during training
* Findings so far
* Deviations from the official gsplat docs



## Related

* Official repo: https://github.com/nerfstudio-project/gsplat
* Windows install docs: `gsplat-1.6.0/docs/INSTALL_WIN.md`
* Benchmark scripts: `gsplat-1.5.3/examples/benchmarks/basic.sh` and `mcmc.sh`
* Our trainer (in the Taletoreum repo): `src/terrestrial_decolonization/pipeline/train.py`
* SuperSplat, for viewing the splats: https://superspl.at/editor



## Quick start

Run everything from this folder, one command at a time, never two at once. Each step has its own section below.

1. Set up gsplat 1.5.3:

```bat
setup.bat 153
```

2. Find the camera poses for the two RealityScan scenes:

```bat
run_sfm.bat stump_rs --no-masks
```

```bat
run_sfm.bat amorphophallus_rs --no-masks
```

3. Train each scene for 7000 steps:

```bat
run_scene.bat 153 7k stump
```

```bat
run_scene.bat 153 7k stump_rs
```

```bat
run_scene.bat 153 7k amorphophallus_rs
```

4. Compare all runs:

```bat
python compare.py
```

5. Train the full 30000 steps, starting the GPU log first (see Training):

```bat
run_scene.bat 153 30k stump mcmc
```

6. Open the splats in SuperSplat (see Reviewing results)



## Versions

* `153`: gsplat v1.5.3, the latest tagged release and the version Taletoreum uses. Commit 937e299, clone `gsplat-1.5.3`, env `gsplat153`
* `160`: gsplat main, which calls itself 1.6.0 but is not released yet. Pinned at commit 512d366 (2026-09-19), clone `gsplat-1.6.0`, env `gsplat160`

Both use torch 2.9.1 cu128, the version main's examples require, so the comparison is fair.

1.6.0 does not build on the lab PC yet: its link step fails on two missing symbols in the 3DGUT rasterizer. Use `153` until that is fixed. Every command below takes `160` the same way once it builds.



## Setup

1. Copy this whole folder to the lab PC, to a short path with no spaces, for example `D:\hyw\gsplat-experiment`
2. Double click `setup.bat`. It sets up both versions. `setup.bat 153` or `setup.bat 160` sets up one
3. If no Visual Studio or portable MSVC is found, it downloads Microsoft's build tools and asks you to accept the Microsoft license in the window. It reuses `HY-World-Experimentation\tools\msvc` when that folder sits next to this one
4. The setup ends with a check per version (compiled gsplat, a small render test on the GPU, fused-ssim, pycolmap, the COLMAP parser) and opens a ready prompt


### Notes

* The first run compiles gsplat and fused-ssim and takes a long time
* Run `setup.bat` again after a reboot. It only installs what is missing



## Scenes and commands

The scenes:

* `stump`: the official Mip-NeRF 360 stump with its official COLMAP camera poses, trained at quarter size as in `basic.sh`
* `stump_rs`: the same 125 quarter size images with camera poses from RealityScan, to compare against the official poses and to see which parts no camera covers
* `amorphophallus_rs`: the 360 the frontend serves, all 240 frames of `orbit_front_centre.mp4` (1280x720) from the Taletoreum repo, with camera poses from RealityScan

The commands:

* `run_sfm.bat <scene> [--no-masks] [--force]`: RealityScan camera poses for `stump_rs` or `amorphophallus_rs`
* `run_scene.bat <153|160> <7k|30k> <scene> [mcmc] [packed]`: trains, evaluates every saved checkpoint, then prints a summary of the run
* `python compare.py`: every run in one table, with the differences between versions
* `python compare.py --run results\<version>\<length>\<scene>`: the summary of one run again


### Notes

* `7k` adds `--max_steps 7000 --save_steps 7000` to the official command. `30k` is the official command as is, with checkpoints at 7000 and 30000 steps
* `mcmc` trains with the official MCMC benchmark (`mcmc.sh`) instead of the default one: the `mcmc` config and `--strategy.cap-max 1000000`, so there are never more than 1 million Gaussians
* `packed` adds the trainer's own `--packed` flag: less GPU memory for each image, slightly slower
* `mcmc` and `packed` can be combined, in any order, and work the same on both versions
* Results go to `results\<version>\<length>\<scene>`, where length is `7k` or `30k` plus `_mcmc` and `_packed` when used, for example `results\153\30k_mcmc\stump`
* `run_stump.bat <153|160> <7k|30k> [mcmc] [packed]` is the same as `run_scene.bat` with `stump`



## Camera poses with RealityScan

RealityScan finds the camera poses with the same steps as the Taletoreum pipeline: add the frames, align, keep the largest connected group of cameras, export COLMAP. `stump` needs no step here, it ships with official COLMAP poses.

1. Run each scene:

```bat
run_sfm.bat stump_rs --no-masks
```

```bat
run_sfm.bat amorphophallus_rs --no-masks
```

2. Each ends with how many images got a pose (`registered images: X of N`), the number of 3D points, and the names of up to 20 images with no pose
3. To see the cameras, open `data\<scene>\realityscan\project.rsproj` in RealityScan. Look from above and from the sides for areas with no cameras and no points


### Notes

* Use `--no-masks`. With RealityScan's AI masks on, as in Taletoreum, `stump_rs` lost cameras and points and `amorphophallus_rs` got no points at all (see Findings)
* The export goes to `data\<scene>\colmap`. Running the same scene again only checks that export. Add `--force` to run RealityScan again
* The export is COLMAP text plus the same model as `.bin` files, the format the official datasets ship, which gsplat 1.5.3 needs
* RealityScan is looked for in `C:\Program Files\Epic Games\RealityScan`. If it is installed elsewhere, run `set "RS_DIR=<folder>"` in the same window first
* The Amorphophallus footage is AI generated and covers about 238 degrees, not a full circle. The plant faces the camera in every frame while the background turns, so RealityScan aligns on the background and the plant comes out smeared
* Both RealityScan scenes train with `--data_factor 1`: `stump_rs` uses `images_4`, already quarter size, so it matches `stump`, and the Amorphophallus frames are used at full size
* A hole that shows up with both the official and the RealityScan poses means the cameras never saw that part, not that the poses are wrong



## Training

### 7k

Train each scene, then compare:

```bat
run_scene.bat 153 7k stump
```

```bat
run_scene.bat 153 7k stump_rs
```

```bat
run_scene.bat 153 7k amorphophallus_rs
```

```bat
python compare.py
```


### 30k

1. Open a second Command Prompt in this folder and start the GPU log. It records memory, temperature and power every 5 seconds, so a crash leaves a record:

```bat
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,temperature.gpu,power.draw,utilization.gpu --format=csv -l 5 -f gpu_log.csv
```

2. In the first window, train with MCMC:

```bat
run_scene.bat 153 30k stump mcmc
```

3. Stop the log with Ctrl + C when the run ends
4. If the run finishes, train the other scenes the same way, for example `run_scene.bat 153 30k stump_rs mcmc`


### Notes

* MCMC is the first choice for 30k. In gsplat's own benchmark on the Mip-NeRF 360 scenes, MCMC capped at 1 million Gaussians reaches PSNR 29.18 with 1.98 GB, against 29.00 with 5.62 GB for the default
* The default trainer keeps adding Gaussians until step 15000, so memory peaks around the middle of a 30k run. On 1.5.3 it peaks higher because of the opacity reset bug under Findings
* `packed` only shrinks the memory for each image, not the Gaussians. It is not needed with `mcmc`
* MCMC and default are different training methods, so compare `mcmc` runs with each other
* The first evaluation downloads the LPIPS network weights, so it needs internet
* The first `stump` run writes `images_4_png` into the dataset, which gsplat's parser makes because stump's `images_4` files are `.JPG`



## Reviewing results

Every run ends with a summary like this:

```
Run summary: results\153\30k_mcmc\stump
  splat at step 7000: 1,000,000 Gaussians, 236 MB, ...\ply\point_cloud_6999.ply
  splat at step 30000: 1,000,000 Gaussians, 236 MB, ...\ply\point_cloud_29999.ply
  step 7000: PSNR ..., SSIM ..., LPIPS ..., training time ... s, peak GPU memory ... GiB
```

The Gaussian count is read from the `.ply` file itself, one point per Gaussian.

To view a splat, open https://superspl.at/editor and drag the `.ply` onto the page. The file stays on the PC.


### Notes

* The step in the file name counts from zero: `point_cloud_6999.ply` is step 7000, `point_cloud_29999.ply` step 30000. A 30k run saves both
* Running the same command again overwrites that run. Copy the folder out of `results` first to keep it
* Compare a `stump_rs` splat with the `stump` splat of the same version and length
* Runs made before `--save_ply` was added have no `.ply`. Export one from the checkpoint with gsplat's own `export_splats`, the same function the flag uses. For 1.5.3 at 7k, from this folder:

```bat
%USERPROFILE%\AppData\Local\miniconda3\envs\gsplat153\python.exe -c "import torch, os; from gsplat import export_splats; c = torch.load(r'results\153\7k\stump\ckpts\ckpt_6999_rank0.pt', map_location='cpu'); s = c['splats']; os.makedirs(r'results\153\7k\stump\ply', exist_ok=True); export_splats(means=s['means'], scales=s['scales'], quats=s['quats'], opacities=s['opacities'], sh0=s['sh0'], shN=s['shN'], format='ply', save_to=r'results\153\7k\stump\ply\point_cloud_6999.ply'); print('saved', len(s['means']), 'Gaussians')"
```



## Crashes during training

A run that runs out of GPU memory stops with an error in the window, or slows to a crawl when the NVIDIA driver moves the overflow into system RAM. Neither restarts the PC. If the whole PC restarts with a blue screen, the fault is below the trainer: the graphics driver, the hardware, or Windows' hypervisor layer. These steps need no admin rights.

1. Read the stop code and the time of the last crashes. If it says access denied, lab IT can read it:

```bat
powershell -Command "Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001,41} -MaxEvents 6 | Format-List TimeCreated, Id, Message"
```

2. Check how big the run was at step 7000 in `results\<version>\<length>\<scene>\stats\train_step6999_rank0.json`. `mem` is the peak GPU memory in GiB and `num_GS` the number of Gaussians
3. Check the end of `gpu_log.csv` for memory near 12 GB, temperature, and power just before the crash
4. Note the driver version from the top line of `nvidia-smi`


### Notes

* If an `mcmc` run, which stays near 2 GB, also crashes, it is a lab PC problem. Give lab IT the stop codes, the times, and that each crash happened under sustained full GPU load
* The last lines of `gpu_log.csv` before a crash can be missing



## Findings

* gsplat 1.5.3 never resets opacity: `gsplat/strategy/default.py:195` reads `step % self.reset_every == 0 & step > 0`, which is always false. 1.6.0 fixes it. Taletoreum's trainer uses 1.5.3 `DefaultStrategy`, so it is affected too
* RealityScan's AI masks keep only the main object in each image and ignore the rest. With them on, `stump_rs` got fewer cameras and points than the official poses, and `amorphophallus_rs` got no points, because its plant shows no parallax once the turning background is masked out. With `--no-masks` both splats look much better
* 30k stump runs restarted the lab PC twice: the default config about halfway, with a blue screen naming the hypervisor, and `packed` at about 34%. HY-World earlier crashed it with DPC_WATCHDOG_VIOLATION, also under full GPU load. The stop codes and the memory at step 7000 are still to be checked with the steps under Crashes during training
* 1.6.0 falls back to a slower SSIM written in plain torch if fused-ssim is missing. The setup checks that fused-ssim is installed for both versions



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
