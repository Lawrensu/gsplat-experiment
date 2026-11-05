@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Runs the official gsplat Mip-NeRF 360 benchmark command (examples/benchmarks/basic.sh)
rem for the stump scene only: one training run, then one evaluation run per saved checkpoint.
rem Usage: run_stump.bat <153|160> <7k|30k>
rem   153   gsplat 1.5.3, clone gsplat-1.5.3, conda env gsplat153
rem   160   gsplat 1.6.0, clone gsplat-1.6.0, conda env gsplat160
rem   7k    adds --max_steps 7000 --save_steps 7000 to the training run (checkpoint at step 7000)
rem   30k   plain defaults (checkpoints at steps 7000 and 30000, both get evaluated)
rem Results go to results\<153|160>\<7k|30k>\stump. Run the two versions one after the other,
rem not at the same time: the first run writes images_4_png into the dataset folder.

set "VER=%~1"
set "LEN=%~2"
if "%VER%"=="" goto usage
if "%LEN%"=="" goto usage
if not "%~3"=="" goto usage
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

set "ENV=gsplat%VER%"
set "EXAMPLES=%~dp0%CLONE%\examples"
set "DATA=%~dp0data\360_v2\stump"
set "RES=%~dp0results\%VER%\%LEN%\stump"
set "PYTHONUTF8=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "CUDA_VISIBLE_DEVICES=0"

if not exist "%EXAMPLES%\simple_trainer.py" echo ERROR: %EXAMPLES%\simple_trainer.py not found. Run setup.bat first. & goto fail_quiet
if not exist "%DATA%\sparse" echo ERROR: dataset not found at %DATA% & goto fail_quiet

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

set COMMON=--disable_viewer --data_factor 4 --render_traj_path ellipse --data_dir "%DATA%" --result_dir "%RES%"

rem ---- 1. Train without eval ----
echo.
echo ==== %CLONE% stump %LEN%: training, started %DATE% %TIME% ====
echo python simple_trainer.py default --eval_steps -1 %COMMON% %EXTRA%
python simple_trainer.py default --eval_steps -1 %COMMON% %EXTRA%
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
echo ==== %CLONE% stump %LEN%: evaluation of %~nx1 ====
echo python simple_trainer.py default %COMMON% --ckpt "%~1"
python simple_trainer.py default %COMMON% --ckpt "%~1"
if errorlevel 1 set "EVALFAIL=1"
exit /b 0

:usage
echo Usage: run_stump.bat ^<153^|160^> ^<7k^|30k^>
echo   153 = gsplat 1.5.3, 160 = gsplat 1.6.0
echo   7k  = stop at 7000 steps, 30k = the full official 30000 steps
pause
exit /b 1

:fail
echo.
echo ERROR: %FAILED% failed (see messages above).
:fail_quiet
pause
exit /b 1
