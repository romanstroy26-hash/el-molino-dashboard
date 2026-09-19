@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PY=
where py >nul 2>&1 && set PY=py
if not defined PY (
    where python >nul 2>&1 && set PY=python
)
if not defined PY (
    echo Не найден Python на этом компьютере.
    echo Установи его с https://python.org/downloads ^(обязательно отметь галочку "Add python.exe to PATH" при установке^), затем запусти этот файл снова.
    echo.
    pause
    exit /b
)

%PY% -m pip show streamlit >nul 2>&1
if errorlevel 1 (
    echo Устанавливаю нужные библиотеки, один раз, подождите минуту-две...
    %PY% -m pip install -r requirements.txt --quiet
)

if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit" >nul 2>&1
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

%PY% -m streamlit run dashboard.py

echo.
pause
