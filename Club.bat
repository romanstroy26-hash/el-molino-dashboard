@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PY=
where py >nul 2>&1 && set PY=py
if not defined PY (
    where python >nul 2>&1 && set PY=python
)
if not defined PY (
    echo Python не найден. Установите Python и повторите запуск.
    pause
    exit /b 1
)

%PY% -c "import fastapi, uvicorn, httpx" >nul 2>&1
if errorlevel 1 (
    echo Устанавливаю зависимости El Molino...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

echo Клиентское приложение: http://127.0.0.1:8000/
echo Панель сотрудника: http://127.0.0.1:8000/staff.html
%PY% -m uvicorn api:app --host 127.0.0.1 --port 8000
pause
