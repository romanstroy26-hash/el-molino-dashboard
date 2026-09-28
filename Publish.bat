@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ===========================================================================
rem  Publish.bat -- одна кнопка: "отправить изменения в GitHub".
rem
rem  Что делает:
rem    1. Копирует файлы программы из этой папки в папку репозитория
rem       (ту, которую завёл GitHub Desktop). НЕ копирует .env, базу и
rem       выгрузки Wansoft -- им в GitHub не место.
rem    2. Делает коммит.
rem    3. Отправляет в GitHub ВСЁ, что ещё не отправлено -- в том числе
rem       коммиты с прошлых запусков, если тогда отправка сорвалась.
rem    4. Streamlit Cloud сам замечает отправку и пересобирает дашборд --
rem       через пару минут новая версия уже в телефоне.
rem
rem  Папку репозитория можно поменять здесь (если GitHub Desktop держит
rem  её в другом месте):
rem ===========================================================================
if not defined REPO_DIR set "REPO_DIR=%USERPROFILE%\Documents\GitHub\el-molino-dashboard"

echo ============================================================
echo   El Molino -- публикация в GitHub
echo   Откуда: %CD%
echo   Куда:   %REPO_DIR%
echo ============================================================
echo.

if not exist "%REPO_DIR%\.git" (
    echo ОШИБКА: по пути "%REPO_DIR%" нет репозитория.
    echo.
    echo Открой GitHub Desktop, посмотри Repository -^> Show in Explorer,
    echo и впиши правильный путь в строку REPO_DIR в начале этого файла.
    goto :fin_error
)

rem --- Ищем git: сначала обычный, потом тот, что внутри GitHub Desktop ---
rem (у GitHub Desktop путь содержит номер версии и меняется после каждого
rem  обновления, поэтому ищем, а не пишем путь жёстко)
set "GIT="
where git >nul 2>&1 && set "GIT=git"
if not defined GIT (
    for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\GitHubDesktop\git.exe" 2^>nul ^| findstr /i "\\cmd\\git.exe"') do set "GIT=%%i"
)
if not defined GIT (
    echo ОШИБКА: не найден git.
    echo Установи GitHub Desktop с https://desktop.github.com либо
    echo обычный Git с https://git-scm.com/download/win и запусти снова.
    goto :fin_error
)

rem --- Копируем только то, что можно публиковать -------------------------
rem  /XD -- какие ПАПКИ не трогать, /XF -- какие ФАЙЛЫ не трогать.
rem  .git исключён обязательно: это сам репозиторий, его портить нельзя.
rem  .env -- пароль от базы. el_molino.db и data -- данные о продажах.
rem
rem  requirements.txt / requirements-api.txt / .python-version -- ОБЩИЕ
rem  файлы с проектом "El Molino Club" (тот же репозиторий, другая
rem  система: API лояльности, живёт своей жизнью в параллельной сессии).
rem  В этой папке requirements.txt -- узкий, только для дашборда; в
rem  репозитории он же -- полный, с пином SQLAlchemy и зависимостями Club.
rem  Раньше эта кнопка молча ЗАТИРАЛА полную версию узкой -- один раз это
rem  уже откатило пин SQLAlchemy и сломало деплой (psycopg2 перестал
rem  ставиться). Поэтому эти три файла теперь не копируются вообще --
rem  если дашборду понадобится новая библиотека, добавь её вручную прямо
rem  в repositorio\requirements.txt, не трогая эту кнопку.
echo Копирую файлы программы...
robocopy "." "%REPO_DIR%" /E ^
    /XD ".git" "data" "__pycache__" "Claude outputs" ^
    /XF ".env" "el_molino.db" "el_molino.db-shm" "el_molino.db-wal" "*.pyc" ^
        "requirements.txt" "requirements-api.txt" ".python-version" ^
    /NFL /NDL /NJH /NJS /R:2 /W:2 >nul
if errorlevel 8 (
    echo ОШИБКА при копировании файлов. Ничего не отправлено.
    goto :fin_error
)

rem --- Готовим коммит, если есть что коммитить ---------------------------
"%GIT%" -C "%REPO_DIR%" add -A
if errorlevel 1 (
    echo ОШИБКА: git не смог подготовить изменения.
    goto :fin_error
)

"%GIT%" -C "%REPO_DIR%" diff --cached --quiet
if errorlevel 1 goto :hay_cambios

echo Новых изменений в файлах нет.
goto :revisar_pendientes

:hay_cambios
echo.
echo Что меняется:
"%GIT%" -C "%REPO_DIR%" diff --cached --stat
echo.

set "MSG=%~1"
if not defined MSG set "MSG=Обновление %DATE% %TIME%"

"%GIT%" -C "%REPO_DIR%" commit -m "%MSG%" >nul
if errorlevel 1 (
    echo ОШИБКА: не удалось сделать коммит.
    goto :fin_error
)

rem --- Сколько коммитов ещё НЕ в GitHub, и нет ли НОВОГО в GitHub --------
rem  Раньше здесь считалось только "сколько у меня неотправленного"
rem  (origin/main..HEAD). Этого мало: если в GitHub тем временем появились
rem  СВОИ новые коммиты (другая сессия/компьютер тоже туда пишет), push
rem  будет отклонён -- а старая версия этой проверки такой случай не
rem  ловила и молча пыталась отправить, получала отказ и говорила "войди
rem  в GitHub", хотя дело было не в этом вообще. Теперь считаем ОБЕ
rem  стороны: и что не отправлено у меня, и что нового появилось в GitHub.
:revisar_pendientes
"%GIT%" -C "%REPO_DIR%" fetch origin main >nul 2>&1

rem  Оба счёта -- через временные файлы, не через for /f: там команда
rem  начинается с ПУТИ В КАВЫЧКАХ (git внутри GitHub Desktop), а cmd в
rem  такой конструкции кавычки перекусывает -- команда не выполняется,
rem  счётчик молча остаётся нулём.
set "TMPF=%TEMP%\el_molino_pendientes.txt"
set "TMPF2=%TEMP%\el_molino_nuevo_en_github.txt"
set "PENDIENTES="
set "NUEVO_EN_GITHUB="
"%GIT%" -C "%REPO_DIR%" rev-list --count origin/main..HEAD > "%TMPF%" 2>nul
if exist "%TMPF%" set /p PENDIENTES=<"%TMPF%"
del "%TMPF%" >nul 2>&1
"%GIT%" -C "%REPO_DIR%" rev-list --count HEAD..origin/main > "%TMPF2%" 2>nul
if exist "%TMPF2%" set /p NUEVO_EN_GITHUB=<"%TMPF2%"
del "%TMPF2%" >nul 2>&1

rem  Не смогли посчитать (нет связи, нет ветки в GitHub) -- НЕ молчим и
rem  не пропускаем: пробуем отправить, пусть git сам скажет, что не так.
if not defined PENDIENTES goto :enviar
if not defined NUEVO_EN_GITHUB goto :enviar

if "%NUEVO_EN_GITHUB%" NEQ "0" (
    echo.
    echo НЕ ОТПРАВЛЕНО: в GitHub появилось %NUEVO_EN_GITHUB% новых
    echo коммит^(ов^), которых нет на этом компьютере -- скорее всего,
    echo из параллельной сессии/компьютера, работающих с тем же
    echo репозиторием:
    "%GIT%" -C "%REPO_DIR%" log --oneline HEAD..origin/main
    echo.
    echo Это НЕ проблема входа в GitHub -- обычный push здесь не поможет и
    echo только запутает. Нужно аккуратно слить обе стороны, посмотрев,
    echo не редактируют ли они одни и те же файлы. Покажи это сообщение
    echo Claude -- дальше он разберётся сам.
    goto :fin_error
)

if "%PENDIENTES%"=="0" (
    echo.
    echo В GitHub уже лежит ровно то же самое. Отправлять нечего.
    goto :fin_ok
)

echo.
echo Не отправлено в GitHub: %PENDIENTES% коммит^(ов^)
"%GIT%" -C "%REPO_DIR%" log --oneline origin/main..HEAD

:enviar
echo.
echo Отправляю...
"%GIT%" -C "%REPO_DIR%" push origin main
if errorlevel 1 goto :fin_push_error

echo.
echo ГОТОВО. Streamlit Cloud увидит изменения сам и пересоберёт дашборд --
echo обычно это занимает 1-3 минуты. Потом открой ссылку в телефоне и
echo нажми "Обновить данные".
goto :fin_ok

:fin_push_error
echo.
echo НЕ ОТПРАВЛЕНО: GitHub не пустил (push отклонён).
echo.
echo Если выше НЕ было сообщения про "новые коммиты в GitHub" -- значит
echo причина, вероятнее всего, в другом: на этом компьютере ещё ни разу
echo не входили в GitHub из обычного git (GitHub Desktop хранит вход
echo отдельно, и этой кнопке он не виден).
echo.
echo Лечится один раз, любым из двух способов:
echo.
echo   1. Запусти этот файл ещё раз и ДОЖДИСЬ окна входа в GitHub --
echo      оно открывается не сразу. Войди в нём. Больше спрашивать не
echo      будет: коммит уже сделан и отправится сам.
echo.
echo   2. Или открой GitHub Desktop -- он покажет "Push origin",
echo      нажми её. Коммит уже готов, он просто уедет.
echo.
goto :fin_error

:fin_ok
echo.
pause
exit /b 0

:fin_error
echo.
pause
exit /b 1
