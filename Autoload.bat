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

rem "--tarea" ставит планировщик Windows. В этом случае окна нет и ждать
rem нажатия клавиши некому -- без этой развилки задача висела бы в памяти
rem до перезагрузки. Сам флаг в программу не передаём, она его не знает.
rem Сначала почта (если она настроена в .env -- иначе correo.py просто
rem скажет об этом и ничего не сделает), потом загрузка в базу. Вместе это
rem вся цепочка: письмо от Wansoft -> файл в data -> цифры в дашборде.
if /i "%~1"=="--tarea" goto :por_horario

%PY% correo.py
echo.
%PY% auto_carga.py %*
echo.
pause
exit /b

:por_horario
%PY% correo.py
%PY% auto_carga.py
exit /b
