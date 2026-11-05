# gsplat Experiment

Builds the official nerfstudio gsplat on the Windows lab PC (RTX 5070, no admin rights) inside conda, and compares two versions on the Mip-NeRF 360 stump scene with gsplat's own trainer. This is the fallback track for the Terrestrial pipeline (RealityScan, gsplat, SOG), before fixing our own gsplat trainer.

This document covers:

* Setting up the lab PC with one click
* Running the stump benchmark for both versions
* Comparing the results
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
* Results go to `results\<version>\<7k|30k>\stump`, with metrics in `stats\` and renders in `renders\`
* The first run writes `images_4_png` into the dataset, which gsplat's parser makes because stump's `images_4` files are `.JPG`
* The first evaluation downloads the LPIPS network weights, so it needs internet
* Note per run: time, peak GPU memory, and how the result looks



## Findings

* gsplat 1.5.3 never resets opacity: `gsplat/strategy/default.py:195` reads `step % self.reset_every == 0 & step > 0`, which is always false. 1.6.0 fixes it. Taletoreum's trainer uses 1.5.3 `DefaultStrategy`, so it is affected too
* 1.6.0 falls back to a slower SSIM written in plain torch if fused-ssim is missing. The setup checks that fused-ssim is installed for both versions



## Deviations

* Portable MSVC 14.44 and the conda-forge CUDA 12.8 compiler instead of Visual Studio Build Tools and the CUDA installer, because both installers need admin rights
* git from conda-forge, because the PC has no git
* torch 2.9.1 cu128 from the PyTorch index first, because the Windows PyPI torch is CPU only
* `pip install -e . --no-build-isolation` instead of `pip install -e .`, because an isolated build would compile against a different, CPU-only torch
* 1.6.0 only: if its experimental extension fails to build, the setup retries once without it. `simple_trainer.py` does not use it
* If `examples/requirements.txt` fails on `nvidia-ncore`, `ppisp` or `fused-bilagrid`, that one line is skipped. None of them are used when training on a COLMAP dataset
