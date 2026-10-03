@echo off
rem read-image: start the MCP server with the first Python 3 that actually runs.
rem Order: py -3 -> python -> python3 -> per-user installs -> bundled Codex runtime.
setlocal
set "SCRIPT=%~dp0mcp_server.py"
set "PYCHECK=import sys; sys.exit(0 if sys.version_info[0]==3 else 1)"

py -3 -c "%PYCHECK%" >nul 2>nul
if not errorlevel 1 (
  py -3 "%SCRIPT%" %*
  exit /b 0
)

python -c "%PYCHECK%" >nul 2>nul
if not errorlevel 1 (
  python "%SCRIPT%" %*
  exit /b 0
)

python3 -c "%PYCHECK%" >nul 2>nul
if not errorlevel 1 (
  python3 "%SCRIPT%" %*
  exit /b 0
)

rem Per-user installs, e.g. %LOCALAPPDATA%\Programs\Python\Python314\python.exe
if defined LOCALAPPDATA (
  for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\python.exe" 2^>nul') do (
    "%%~fP" -c "%PYCHECK%" >nul 2>nul
    if not errorlevel 1 (
      "%%~fP" "%SCRIPT%" %*
      exit /b 0
    )
  )
)

rem Bundled Codex runtime (always present with the desktop app).
set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PYTHON%" (
  "%CODEX_PYTHON%" -c "%PYCHECK%" >nul 2>nul
  if not errorlevel 1 (
    "%CODEX_PYTHON%" "%SCRIPT%" %*
    exit /b 0
  )
)

>&2 echo read-image: no working Python 3 interpreter found. Install Python 3 or add it to PATH.
exit /b 9009
