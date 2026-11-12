@echo off
rem Kept for the commands in the README: the same as run_scene.bat <153|160> <7k|30k> stump [mcmc] [packed]
rem Usage: run_stump.bat <153|160> <7k|30k> [mcmc] [packed]
call "%~dp0run_scene.bat" %1 %2 stump %3 %4
exit /b %errorlevel%
