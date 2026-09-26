# detener_vigilante.ps1 -- останавливает сторожа СОВСЕМ: и текущий
# запущенный процесс, и автозапуск при следующем входе в Windows.
# Запускается не сам по себе, а из Detener_Vigilante.bat (двойной клик).
#
# Почему два действия, а не одно: задачу в планировщике и сам процесс
# vigilar.py смотреть в одиночку бессмысленно -- если убрать только
# задачу, уже запущенный сторож продолжит работать до перезагрузки; если
# убить только процесс, он тут же оживёт заново при следующем входе в
# Windows (для этого задача и существует). Нужны оба шага сразу.

param(
    [string]$Nombre = "El Molino - Vigilante"
)

$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $carpeta "data\vigilante.pid"

Write-Host "============================================================"
Write-Host "  El Molino -- остановка сторожа"
Write-Host "============================================================"
Write-Host ""

# --- 1. Останавливаем сам работающий процесс, если он есть -------------
if (Test-Path $pidFile) {
    $pid_texto = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $pid_num = 0
    if ([int]::TryParse($pid_texto, [ref]$pid_num) -and $pid_num -gt 0) {
        $proceso = Get-Process -Id $pid_num -ErrorAction SilentlyContinue
        if ($proceso) {
            Stop-Process -Id $pid_num -Force
            Write-Host "Сторож (PID $pid_num) остановлен." -ForegroundColor Green
        } else {
            Write-Host "В data\vigilante.pid записан PID $pid_num, но такого процесса уже нет."
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "Файл data\vigilante.pid не найден -- похоже, сторож сейчас не запущен."
}

# --- 2. Отключаем автозапуск, чтобы он не ожил сам при входе в Windows --
$tarea = Get-ScheduledTask -TaskName $Nombre -ErrorAction SilentlyContinue
if ($tarea) {
    Disable-ScheduledTask -TaskName $Nombre | Out-Null
    Write-Host "Автозапуск при входе в Windows отключён (задача '$Nombre')."
} else {
    Write-Host "Задача '$Nombre' в планировщике не найдена -- автозапуска и так нет."
}

Write-Host ""
Write-Host "Готово. Сторож не работает и сам больше не запустится."
Write-Host "Чтобы включить снова -- дважды кликни Schedule.bat."
