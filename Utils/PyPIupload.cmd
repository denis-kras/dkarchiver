@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM run this file in the same location as 'pyproject.toml'.
REM Install 'twine' library: pip install twine

cd "%~dp0"
cd..

REM --- Pick first artifact in dist (wheel preferred, then sdist) ---
if not exist "dist\" (
  echo [ERROR] dist\ folder not found.
  goto :end
)

set "ARTIFACT="
for %%F in ("dist\*.whl") do ( set "ARTIFACT=%%~nxF" & goto :have_artifact )
for %%F in ("dist\*.tar.gz") do ( set "ARTIFACT=%%~nxF" & goto :have_artifact )

echo [ERROR] No files found in dist\ (*.whl or *.tar.gz).
goto :end

:have_artifact
REM Extract repo alias = distribution name (prefix before first '-')
for /f "tokens=1 delims=-" %%A in ("!ARTIFACT!") do set "REPO=%%A"

echo Using repository: "!REPO!"
echo Artifact: "!ARTIFACT!"

REM Basic check.
python -m twine check dist/*
pause

REM Upload the package.
python -m twine upload --repository "!REPO!" dist\*
pause
