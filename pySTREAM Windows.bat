@echo off
rem pySTREAM for Windows: double-click this file to start pySTREAM. It opens in your web browser.
rem The first time, it installs the Python packages pySTREAM needs. This takes a few minutes.
rem pySTREAM stops when you click "Close pySTREAM" on the page or close this window,
rem and by itself a minute after you close its browser tab.

setlocal
cd /d "%~dp0"
title pySTREAM
set "CHECK=import pandas, numpy, numpy_financial, plotly, openpyxl"

rem 1. pySTREAM installed in the .venv folder by this file
if not exist ".venv\Scripts\python.exe" goto find_conda
".venv\Scripts\python.exe" -c "%CHECK%" >nul 2>nul
if errorlevel 1 goto find_conda
goto start_venv

rem 2. The Conda environment pySTREAM_class, if it exists and has everything pySTREAM needs
:find_conda
set "CONDA="
for %%C in (conda.bat) do set "CONDA=%%~$PATH:C"
if not defined CONDA for %%C in (conda.exe) do set "CONDA=%%~$PATH:C"
if not defined CONDA if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined CONDA if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not defined CONDA if exist "%LOCALAPPDATA%\anaconda3\condabin\conda.bat" set "CONDA=%LOCALAPPDATA%\anaconda3\condabin\conda.bat"
if not defined CONDA if exist "%ProgramData%\anaconda3\condabin\conda.bat" set "CONDA=%ProgramData%\anaconda3\condabin\conda.bat"
if not defined CONDA if exist "%ProgramData%\miniconda3\condabin\conda.bat" set "CONDA=%ProgramData%\miniconda3\condabin\conda.bat"
if not defined CONDA goto install
call "%CONDA%" run -n pySTREAM_class python -c "%CHECK%" >nul 2>nul
if errorlevel 1 goto install
goto start_conda

rem 3. First start: install Python packages in the .venv folder (needs Python 3.12 or newer)
:install
echo.
echo Installing pySTREAM. This is only needed the first time and takes a few minutes...
echo.
set "PY="
for %%V in (3.14 3.13 3.12 3.15) do if not defined PY py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
if not defined PY py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=python"
if not defined PY goto no_python
%PY% --version
%PY% -m venv --clear .venv
if errorlevel 1 goto install_failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_failed
echo.
echo pySTREAM is installed.
goto start_venv

:start_venv
echo.
echo pySTREAM opens in your web browser. Keep this window open while you use pySTREAM.
echo.
".venv\Scripts\python.exe" pySTREAM_web.py
if errorlevel 1 goto stopped_with_error
exit /b 0

:start_conda
echo.
echo pySTREAM opens in your web browser. Keep this window open while you use pySTREAM.
echo.
call "%CONDA%" run --no-capture-output -n pySTREAM_class python pySTREAM_web.py
if errorlevel 1 goto stopped_with_error
exit /b 0

:no_python
echo pySTREAM needs Python 3.12 or newer, which was not found on this computer.
echo The Python download page opens in your browser now. Install Python from there,
echo tick "Add python.exe to PATH" in the installer, and then double-click
echo "pySTREAM Windows.bat" again.
start "" "https://www.python.org/downloads/"
goto wait_and_exit

:install_failed
echo.
echo The installation failed; see the messages above.
echo Check your internet connection and try again.
goto wait_and_exit

:stopped_with_error
echo.
echo pySTREAM stopped with an error; see the messages above.

:wait_and_exit
echo.
pause
exit /b 1
