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
rem    4. Облачные сервисы получают новую версию из GitHub. Club в Render
rem       может потребовать Manual Deploy -^> Deploy latest commit.
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

rem --- Не копируем поверх незавершённого merge в GitHub Desktop -------
set "TMPU=%TEMP%\el_molino_unmerged.txt"
"%GIT%" -C "%REPO_DIR%" ls-files -u > "%TMPU%" 2>nul
if errorlevel 1 (
    del "%TMPU%" >nul 2>&1
    echo ОШИБКА: git не смог проверить состояние репозитория.
    goto :fin_error
)
for %%A in ("%TMPU%") do set "UNMERGED_SIZE=%%~zA"
del "%TMPU%" >nul 2>&1
if not "%UNMERGED_SIZE%"=="0" (
    echo ОШИБКА: в GitHub Desktop не завершено слияние веток.
    echo Открой репозиторий, заверши или отмени merge и обнови main,
    echo затем снова запусти Publish.bat.
    goto :fin_error
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
echo Копирую файлы программы...
robocopy "." "%REPO_DIR%" /E ^
    /XD ".git" "data" "__pycache__" "Claude outputs" ^
    /XF ".env" "el_molino.db" "el_molino.db-shm" "el_molino.db-wal" "*.pyc" ^
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

rem --- Сколько коммитов ещё НЕ в GitHub ----------------------------------
rem  Проверять обязательно: коммит мог быть сделан в прошлый раз, а
rem  отправка тогда сорваться (например, не прошёл вход в GitHub). Без
rem  этой проверки такой коммит навсегда остался бы лежать на диске, а
rem  кнопка бодро сообщала бы, что отправлять нечего.
:revisar_pendientes
"%GIT%" -C "%REPO_DIR%" fetch origin main >nul 2>&1

rem  Счёт неотправленного пишем во временный файл, а не читаем через
rem  for /f: там команда начинается с ПУТИ В КАВЫЧКАХ (git внутри GitHub
rem  Desktop), а cmd в такой конструкции кавычки перекусывает -- команда
rem  не выполняется, счётчик молча остаётся нулём, и кнопка врёт, будто
rem  отправлять нечего.
set "TMPF=%TEMP%\el_molino_pendientes.txt"
set "PENDIENTES="
"%GIT%" -C "%REPO_DIR%" rev-list --count origin/main..HEAD > "%TMPF%" 2>nul
if exist "%TMPF%" set /p PENDIENTES=<"%TMPF%"
del "%TMPF%" >nul 2>&1

rem  Не смогли посчитать (нет связи, нет ветки в GitHub) -- НЕ молчим и
rem  не пропускаем: пробуем отправить, пусть git сам скажет, что не так.
if not defined PENDIENTES goto :enviar

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
echo ГОТОВО. Код отправлен в GitHub.
echo Для Club в Render проверь новую сборку. Если её нет, выбери
echo Manual Deploy -^> Deploy latest commit в el-molino-club.
goto :fin_ok

:fin_push_error
echo.
echo НЕ ОТПРАВЛЕНО: GitHub не пустил.
echo.
echo Почти всегда причина одна: на этом компьютере ещё ни разу не входили
echo в GitHub из обычного git (GitHub Desktop хранит вход отдельно, и
echo этой кнопке он не виден).
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
