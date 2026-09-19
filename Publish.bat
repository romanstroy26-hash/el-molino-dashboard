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
rem    2. Делает коммит и push.
rem    3. Streamlit Cloud сам замечает push и пересобирает дашборд --
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
    echo.
    pause
    exit /b 1
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
    echo.
    pause
    exit /b 1
)

rem --- Копируем только то, что можно публиковать -------------------------
rem  /XD -- какие ПАПКИ не трогать, /XF -- какие ФАЙЛЫ не трогать.
rem  .git исключён обязательно: это сам репозиторий, его портить нельзя.
rem  .env -- пароль от базы. el_molino.db и data -- данные о продажах.
echo Копирую файлы программы...
robocopy "." "%REPO_DIR%" /E ^
    /XD ".git" "data" "__pycache__" ".streamlit\cache" "Claude outputs" ^
    /XF ".env" "el_molino.db" "el_molino.db-shm" "el_molino.db-wal" "*.pyc" ^
    /NFL /NDL /NJH /NJS /R:2 /W:2 >nul
if errorlevel 8 (
    echo ОШИБКА при копировании файлов. Ничего не отправлено.
    echo.
    pause
    exit /b 1
)

rem --- Готовим коммит ----------------------------------------------------
"%GIT%" -C "%REPO_DIR%" add -A
if errorlevel 1 (
    echo ОШИБКА: git не смог подготовить изменения.
    echo.
    pause
    exit /b 1
)

"%GIT%" -C "%REPO_DIR%" diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo Изменений нет -- в GitHub уже лежит ровно то же самое.
    echo Отправлять нечего.
    echo.
    pause
    exit /b 0
)

echo.
echo Что отправляется:
"%GIT%" -C "%REPO_DIR%" diff --cached --stat
echo.

set "MSG=%~1"
if not defined MSG set "MSG=Обновление %DATE% %TIME%"

"%GIT%" -C "%REPO_DIR%" commit -m "%MSG%" >nul
if errorlevel 1 (
    echo ОШИБКА: не удалось сделать коммит.
    echo.
    pause
    exit /b 1
)

echo Отправляю в GitHub...
"%GIT%" -C "%REPO_DIR%" push origin main
if errorlevel 1 (
    echo.
    echo ОШИБКА при отправке. Чаще всего это значит, что нужно один раз
    echo войти в аккаунт: открой GitHub Desktop и нажми там Push origin --
    echo он спросит логин. После этого эта кнопка заработает сама.
    echo.
    pause
    exit /b 1
)

echo.
echo ГОТОВО. Streamlit Cloud увидит изменения сам и пересоберёт дашборд --
echo обычно это занимает 1-3 минуты. Потом открой ссылку в телефоне и
echo нажми "Обновить данные".
echo.
pause
