@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Camera poses with RealityScan for one scene: data\<scene>\frames in, data\<scene>\colmap out
rem (sparse\0 and undistorted images), the same RealityScan steps as the Taletoreum pipeline.
rem Usage: run_sfm.bat <scene> [--no-masks] [--force]
rem   --no-masks   align without RealityScan's AI masks
rem   --force      delete the existing export and run again
rem RealityScan is looked for in C:\Program Files\Epic Games\RealityScan. If it sits elsewhere:
rem   set "RS_DIR=D:\path\to\RealityScan"   before running this file.

if "%~1"=="" goto usage
set "PYTHONUTF8=1"

rem ---- Find a gsplat env python (the script only needs the standard library) ----
set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%~dp0tools\miniforge3") do if not defined CONDA_ROOT if exist "%%~D\Scripts\activate.bat" set "CONDA_ROOT=%%~D"
if not defined CONDA_ROOT echo ERROR: No conda found. Run setup.bat first. & goto fail
set "PY="
for %%E in (gsplat160 gsplat153) do if not defined PY if exist "%CONDA_ROOT%\envs\%%E\python.exe" set "PY=%CONDA_ROOT%\envs\%%E\python.exe"
if not defined PY echo ERROR: No gsplat conda env found. Run setup.bat first. & goto fail

"%PY%" "%~dp0realityscan_sfm.py" %*
if errorlevel 1 goto fail
echo.
echo Next: run_scene.bat ^<153^|160^> 7k %~1
pause
exit /b 0

:usage
echo Usage: run_sfm.bat ^<scene^> [--no-masks] [--force]
echo   for example: run_sfm.bat amorphophallus
pause
exit /b 1

:fail
echo.
echo ERROR: RealityScan step failed (see messages above).
pause
exit /b 1
