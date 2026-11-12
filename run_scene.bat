@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Runs the official gsplat benchmark command (examples/benchmarks/basic.sh) for one scene:
rem one training run, then one evaluation run per saved checkpoint.
rem Usage: run_scene.bat <153|160> <7k|30k> <scene> [mcmc] [packed]
rem   153     gsplat 1.5.3, clone gsplat-1.5.3, conda env gsplat153
rem   160     gsplat 1.6.0, clone gsplat-1.6.0, conda env gsplat160
rem   7k      adds --max_steps 7000 --save_steps 7000 to the training run (checkpoint at step 7000)
rem   30k     plain defaults (checkpoints at steps 7000 and 30000, both get evaluated)
rem   stump   data\360_v2\stump with --data_factor 4, as in basic.sh
rem   other   data\<scene>\colmap from run_sfm.bat, with --data_factor 1 (the frames are used at full size).
rem           stump_rs is stump's images_4 with RealityScan poses, so factor 1 there matches factor 4 above
rem   mcmc    the official mcmc benchmark instead (examples/benchmarks/mcmc.sh): the mcmc config with
rem           --strategy.cap-max 1000000, so the number of Gaussians, and with it the memory, has a ceiling
rem   packed  the trainer's own --packed flag: less GPU memory, slightly slower. Works with either config
rem Results go to results\<153|160>\<7k|30k>[_mcmc][_packed]\<scene>, the splat in its ply folder. Run one at a time.

rem Gaussian ceiling for mcmc, the CAP_MAX value in the official mcmc.sh
set "CAP_MAX=1000000"

set "VER=%~1"
set "LEN=%~2"
set "SCENE=%~3"
if "%VER%"=="" goto usage
if "%LEN%"=="" goto usage
if "%SCENE%"=="" goto usage

rem ---- Optional mcmc and packed, in any order ----
set "HAS_MCMC="
set "HAS_PACKED="
:opt_loop
if "%~4"=="" goto opts_done
set "OPT_OK="
if /i "%~4"=="mcmc" set "HAS_MCMC=1" & set "OPT_OK=1"
if /i "%~4"=="packed" set "HAS_PACKED=1" & set "OPT_OK=1"
if not defined OPT_OK goto usage
shift /4
goto opt_loop
:opts_done
set "CONFIG=default"
set "OPTS="
set "TAG="
if defined HAS_MCMC set "CONFIG=mcmc" & set "OPTS=--strategy.cap-max %CAP_MAX%" & set "TAG=_mcmc"
if defined HAS_PACKED set "OPTS=%OPTS% --packed" & set "TAG=%TAG%_packed"
set "RUN=%LEN%%TAG%"

set "CLONE="
if "%VER%"=="153" set "CLONE=gsplat-1.5.3"
if "%VER%"=="160" set "CLONE=gsplat-1.6.0"
if not defined CLONE goto usage
set "EXTRA="
if /i "%LEN%"=="7k" set "EXTRA=--max_steps 7000 --save_steps 7000"
if /i "%LEN%"=="7k" goto len_ok
if /i "%LEN%"=="30k" goto len_ok
goto usage
:len_ok

if /i "%SCENE%"=="stump" (
    set "DATA=%~dp0data\360_v2\stump"
    set "FACTOR=4"
) else (
    set "DATA=%~dp0data\%SCENE%\colmap"
    set "FACTOR=1"
)

set "ENV=gsplat%VER%"
set "EXAMPLES=%~dp0%CLONE%\examples"
set "RES=%~dp0results\%VER%\%RUN%\%SCENE%"
set "PYTHONUTF8=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "CUDA_VISIBLE_DEVICES=0"

if not exist "%EXAMPLES%\simple_trainer.py" echo ERROR: %EXAMPLES%\simple_trainer.py not found. Run setup.bat first. & goto fail_quiet
if not exist "%DATA%\sparse" echo ERROR: dataset not found at %DATA%. For a new scene run run_sfm.bat %SCENE% first. & goto fail_quiet

rem ---- Find conda (same places as setup.bat) ----
set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%~dp0tools\miniforge3") do if not defined CONDA_ROOT if exist "%%~D\Scripts\activate.bat" set "CONDA_ROOT=%%~D"
if not defined CONDA_ROOT echo ERROR: No conda found. Run setup.bat first. & goto fail_quiet
echo Using conda at: %CONDA_ROOT%
if not exist "%CONDA_ROOT%\envs\%ENV%\python.exe" echo ERROR: conda env %ENV% not found. Run setup.bat first. & goto fail_quiet
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
if errorlevel 1 set "FAILED=Activating conda base" & goto fail
call conda activate %ENV%
if errorlevel 1 set "FAILED=Activating conda env %ENV%" & goto fail

cd /d "%EXAMPLES%"
if errorlevel 1 set "FAILED=Changing to %EXAMPLES%" & goto fail

rem The mcmc and packed options go to both training and evaluation, as in mcmc.sh
set COMMON=--disable_viewer --data_factor %FACTOR% %OPTS% --render_traj_path ellipse --data_dir "%DATA%" --result_dir "%RES%"

rem ---- 1. Train without eval ----
echo.
echo ==== %CLONE% %SCENE% %RUN%: training, started %DATE% %TIME% ====
rem --save_ply is the trainer's own flag: it adds ply\point_cloud_<step>.ply at steps 7000 and
rem 30000 (and the last step) for viewing, for example in SuperSplat. Training is unchanged.
echo python simple_trainer.py %CONFIG% --eval_steps -1 --save_ply %COMMON% %EXTRA%
python simple_trainer.py %CONFIG% --eval_steps -1 --save_ply %COMMON% %EXTRA%
if errorlevel 1 set "FAILED=Training" & goto fail

rem ---- 2. Evaluate and render from each checkpoint ----
if not exist "%RES%\ckpts\*" set "FAILED=No checkpoints found in %RES%\ckpts" & goto fail
set "EVALFAIL="
for %%C in ("%RES%\ckpts\*") do if not defined EVALFAIL call :eval_ckpt "%%~fC"
if defined EVALFAIL set "FAILED=Evaluation" & goto fail

echo.
echo ==== Done %DATE% %TIME% ====
echo Stats are in %RES%\stats. Compare runs with: python compare.py
pause
exit /b 0

:eval_ckpt
echo.
echo ==== %CLONE% %SCENE% %RUN%: evaluation of %~nx1 ====
echo python simple_trainer.py %CONFIG% %COMMON% --ckpt "%~1"
python simple_trainer.py %CONFIG% %COMMON% --ckpt "%~1"
if errorlevel 1 set "EVALFAIL=1"
exit /b 0

:usage
echo Usage: run_scene.bat ^<153^|160^> ^<7k^|30k^> ^<scene^> [mcmc] [packed]
echo   153 = gsplat 1.5.3, 160 = gsplat 1.6.0
echo   7k  = stop at 7000 steps, 30k = the full official 30000 steps
echo   scene = stump, or a folder under data made with run_sfm.bat, for example amorphophallus_rs
echo   mcmc = the official mcmc benchmark, at most 1 million Gaussians
echo   packed = less GPU memory, slightly slower
pause
exit /b 1

:fail
echo.
echo ERROR: %FAILED% failed (see messages above).
:fail_quiet
pause
exit /b 1
