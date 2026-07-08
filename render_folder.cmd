@echo off
setlocal
python "%~dp0render_all_vehicles.py" %*
exit /b %ERRORLEVEL%
