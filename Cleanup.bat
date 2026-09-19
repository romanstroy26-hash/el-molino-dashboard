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

%PY% -m pip show sqlalchemy >nul 2>&1
if errorlevel 1 (
    echo Устанавливаю нужные библиотеки, один раз, подождите минуту-две...
    %PY% -m pip install -r requirements.txt --quiet
)

%PY% limpiar_duplicados.py --aplicar

echo.
pause
