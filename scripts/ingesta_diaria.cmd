@echo off
rem Ingesta diaria del catalogo para el Programador de tareas de Windows.
rem Deja el registro en data\logs\ingesta.log y devuelve el codigo de salida de la ingesta.
setlocal
cd /d "%~dp0.."
if not exist "data\logs" mkdir "data\logs"
".venv\Scripts\python.exe" -m app.ingest %* >> "data\logs\ingesta.log" 2>&1
exit /b %ERRORLEVEL%
