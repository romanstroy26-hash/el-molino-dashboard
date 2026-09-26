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

rem "--tarea" -- так его запускает vigilante_oculto.vbs (планировщик,
rem окна не видно никому). Единственное отличие от обычного запуска --
rem без "pause" в конце (спросить некого).
rem
rem Здесь НЕТ цикла "перезапустить, если упал" специально: если vigilar.py
rem завершился -- по команде Detener_Vigilante.bat или сам по себе --
rem пусть он останется завершённым. Обёртка, которая упрямо поднимает
rem процесс заново, сделала бы "остановить" ненастоящим -- сторож ожил бы
rem через полминуты сам, вопреки явной команде его выключить. Устойчивость
rem к сбоям -- дело самого vigilar.py (там всё тело цикла в try/except),
rem а не этого файла.
if /i "%~1"=="--tarea" (
    %PY% vigilar.py
    exit /b
)

rem Окно остаётся открытым и живым -- здесь видно, что сторож находит и
rem грузит, в реальном времени. Закрыть окно или нажать Ctrl+C -- это и
rem есть остановка. Постоянная, невидимая работа -- через Schedule.bat,
rem это окно для неё не нужно.
%PY% vigilar.py
echo.
pause
