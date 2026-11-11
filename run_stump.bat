@echo off
rem Kept for the commands in the README: the same as run_scene.bat <153|160> <7k|30k> stump
rem Usage: run_stump.bat <153|160> <7k|30k>
call "%~dp0run_scene.bat" %1 %2 stump
exit /b %errorlevel%
