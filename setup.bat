@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem One click setup of the official nerfstudio gsplat for the lab PC, two versions side by side.
rem Safe to run again: it only installs what is missing. Optional argument:
rem   (none)  set up 153 and then 160
rem   153     gsplat v1.5.3   clone gsplat-1.5.3, conda env gsplat153
rem   160     gsplat 1.6.0 (main, pinned commit)   clone gsplat-1.6.0, conda env gsplat160
rem The commits are pinned in setup_env.py.

set "TOOLS=%~dp0tools"
set "VERSIONS=153 160"
if /i "%~1"=="153" set "VERSIONS=153"
if /i "%~1"=="160" set "VERSIONS=160"
if not "%~1"=="" if /i not "%~1"=="153" if /i not "%~1"=="160" goto err_arg
set "S153=not run"
set "S160=not run"
set "PYVER=3.11"
rem Windows defaults to cp1252. UTF-8 keeps reading and printing paths safe.
set "PYTHONUTF8=1"

echo ==========================================
echo  gsplat setup, versions: %VERSIONS%
echo ==========================================

rem ---- 0. Checks that assume nothing about this PC ----
where curl.exe >nul 2>&1
if errorlevel 1 set "FAILED=curl.exe not found (it ships with Windows 10 version 1803 and newer)" & goto fail
where tar.exe >nul 2>&1
if errorlevel 1 set "FAILED=tar.exe not found (it ships with Windows 10 version 1803 and newer)" & goto fail
set "HERE=%~dp0"
if not "%HERE: =%"=="%HERE%" goto err_path_space
if not "%HERE:~40,1%"=="" echo WARNING: this folder path is long (%HERE%). CUDA builds can fail above the 260 character path limit, and long paths cannot be enabled without admin. A short path like D:\gsplat is safer.
set "MINGB=40"
if /i "%VERSIONS%"=="153 160" set "MINGB=70"
set "FREEGB="
set "DRV=%~d0"
for /f %%A in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive %DRV:~0,1%).Free/1GB)" 2^>nul') do set "FREEGB=%%A"
if defined FREEGB if %FREEGB% LSS %MINGB% echo WARNING: only %FREEGB% GB free on %DRV%, versions %VERSIONS% want at least %MINGB% GB.
rem Short, user writable temp folder for pip and compiler builds.
if not exist "%~dp0tmp" mkdir "%~dp0tmp"
set "TMP=%~dp0tmp"
set "TEMP=%~dp0tmp"
if not exist "%~dp0data\360_v2\stump\images_4" echo NOTE: data\360_v2\stump\images_4 not found. Copy the stump scene of the Mip-NeRF 360 dataset to data\360_v2\stump (it needs images_4 and sparse\0) before running the experiment. Setup does not need it.
if not exist "%~dp0data\360_v2\stump\sparse\0" echo NOTE: data\360_v2\stump\sparse\0 not found. Copy the stump scene of the Mip-NeRF 360 dataset to data\360_v2\stump (it needs images_4 and sparse\0) before running the experiment. Setup does not need it.

rem ---- 1. Find conda ----
set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%~dp0tools\miniforge3") do if not defined CONDA_ROOT if exist "%%~D\Scripts\activate.bat" set "CONDA_ROOT=%%~D"
if defined CONDA_ROOT goto have_conda

echo No conda found. Installing Miniforge for this user, no admin needed.
rem The installer /D option must be last and unquoted, so the folder path cannot contain spaces.
set "MFDIR=%TOOLS%\miniforge3"
set "NOSPACE=%MFDIR: =%"
if not "%NOSPACE%"=="%MFDIR%" goto err_space
if not exist "%TOOLS%" mkdir "%TOOLS%"
echo Downloading Miniforge...
curl.exe -L --fail -o "%TOOLS%\Miniforge3-Windows-x86_64.exe" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"
if errorlevel 1 set "FAILED=Downloading Miniforge" & goto fail
echo Running the Miniforge installer, this takes a few minutes...
start /wait "" "%TOOLS%\Miniforge3-Windows-x86_64.exe" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%MFDIR%
if errorlevel 1 set "FAILED=Installing Miniforge" & goto fail
if not exist "%MFDIR%\Scripts\activate.bat" set "FAILED=Installing Miniforge (activate.bat missing afterwards)" & goto fail
del "%TOOLS%\Miniforge3-Windows-x86_64.exe" >nul 2>&1
set "CONDA_ROOT=%MFDIR%"

:have_conda
echo Using conda at: %CONDA_ROOT%

rem ---- 2. Activate conda base ----
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
if errorlevel 1 set "FAILED=Activating conda base" & goto fail

rem ---- 3. Set up each version. One failing version does not stop the other. ----
for %%V in (%VERSIONS%) do call :one %%V
set "LAST="
for %%V in (%VERSIONS%) do set "LAST=%%V"

rem ---- 4. Summary ----
echo.
echo ==========================================
echo  Summary
echo ==========================================
for %%V in (%VERSIONS%) do call :summ %%V
echo.
set "ANYFAIL="
for %%V in (%VERSIONS%) do call :chk %%V
if defined ANYFAIL echo WARNING: at least one version FAILED, see the messages above. Run setup.bat again after fixing the cause.
call set "LASTSTATUS=%%S%LAST%%%"
if /i not "%LASTSTATUS%"=="OK" set "FAILED=gsplat %LAST% (see messages above)" & goto fail

rem ---- 5. Done: leave a ready Command Prompt in examples of the last version ----
if not exist "%TOOLS%\msvc_env.txt" set "FAILED=Reading tools\msvc_env.txt (written by setup_env.py)" & goto fail
set /p MSVC_BAT=<"%TOOLS%\msvc_env.txt"
if not exist "%MSVC_BAT%" set "FAILED=Finding the MSVC environment file %MSVC_BAT%" & goto fail
call "%MSVC_BAT%" >nul
where cl.exe >nul 2>&1
if errorlevel 1 set "FAILED=Loading the MSVC environment from %MSVC_BAT% (cl.exe not found afterwards)" & goto fail
call conda activate gsplat%LAST%
if errorlevel 1 set "FAILED=Activating conda env gsplat%LAST%" & goto fail
set "CUDA_HOME=%CONDA_PREFIX%\Library"
set "CUDA_PATH=%CONDA_PREFIX%\Library"
set "INCLUDE=%CONDA_PREFIX%\Library\include;%INCLUDE%"
set "LIB=%CONDA_PREFIX%\Library\lib;%CONDA_PREFIX%\Library\lib\x64;%LIB%"
set "DISTUTILS_USE_SDK=1"
set "MSSdk=1"
set "TORCH_CUDA_ARCH_LIST=12.0"
set "PYTHONUTF8=1"
if "%LAST%"=="153" set "CLONE=gsplat-1.5.3"
if "%LAST%"=="160" set "CLONE=gsplat-1.6.0"
cd /d "%~dp0%CLONE%\examples"
echo.
echo ==========================================
echo  Setup complete. Environment: gsplat%LAST%
echo  You are in %CLONE%\examples. MSVC, CUDA_HOME, CUDA_PATH,
echo  DISTUTILS_USE_SDK, TORCH_CUDA_ARCH_LIST=12.0 and PYTHONUTF8=1 are set.
echo  Switch version with: conda activate gsplat153  or  conda activate gsplat160
echo ==========================================
cmd /k
exit /b 0

rem ---- Subroutines ----

:one
set "VER=%~1"
set "ENV=gsplat%VER%"
set "S%VER%=FAILED"
echo.
echo ==========================================
echo  gsplat %VER%, conda env %ENV%
echo ==========================================
echo.
echo [1/9] Conda env %ENV% (python %PYVER%)
if exist "%CONDA_ROOT%\envs\%ENV%\python.exe" goto one_have_env
call conda create -y -n %ENV% -c conda-forge --override-channels python=%PYVER%
if errorlevel 1 echo ERROR: Creating conda env %ENV% failed & exit /b 1
:one_have_env
call conda activate %ENV%
if errorlevel 1 echo ERROR: Activating conda env %ENV% failed & exit /b 1
python "%~dp0setup_env.py" %VER%
if errorlevel 1 echo ERROR: setup_env.py %VER% failed, see messages above & exit /b 1
set "S%VER%=OK"
exit /b 0

:summ
echo.
call echo  Result: %%S%~1%%
if exist "%CONDA_ROOT%\envs\gsplat%~1\python.exe" "%CONDA_ROOT%\envs\gsplat%~1\python.exe" "%~dp0setup_env.py" summary %~1
exit /b 0

:chk
call set "ST=%%S%~1%%"
if /i not "%ST%"=="OK" set "ANYFAIL=1"
exit /b 0

:err_arg
echo.
echo ERROR: unknown argument "%~1". Use  setup.bat  or  setup.bat 153  or  setup.bat 160
pause
exit /b 1

:err_path_space
echo.
echo ERROR: this folder path contains spaces:
echo   %HERE%
echo Move this whole folder to a short path without spaces (for example D:\gsplat) and run again.
pause
exit /b 1

:err_space
echo.
echo ERROR: Miniforge cannot be installed into a folder path that contains spaces:
echo   %MFDIR%
echo Move this whole folder to a path without spaces (for example D:\gsplat-experiment) and run setup.bat again.
pause
exit /b 1

:fail
echo.
echo ERROR: setup failed at step: %FAILED%
pause
exit /b 1
