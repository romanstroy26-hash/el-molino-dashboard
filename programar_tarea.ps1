# programar_tarea.ps1 -- ставит сторожа (vigilar.py) в автозагрузку
# Windows. Запускается не сам по себе, а из Schedule.bat (двойной клик).
#
# Раньше здесь стояла задача "раз в день в 11:00" -- под неё нужно было
# точно подбирать время (см. старые версии этого файла). Теперь вместо
# этого -- НЕПРЕРЫВНЫЙ сторож (vigilar.py), который сам смотрит на папки
# каждые 15 секунд, поэтому время суток больше не имеет значения вообще:
# положил файл -- через 15 секунд он в базе, в любой час.
#
# Что делает эта задача в планировщике: при каждом входе в Windows под
# этим пользователем -- без единого окна на экране -- запускает
# vigilante_oculto.vbs, который поднимает vigilar.py и оставляет его
# работать. Сам он практически никогда не завершается (внутри --
# защита от сбоев на каждом цикле, см. vigilar.py), а если его всё же
# остановить явно (Detener_Vigilante.bat) -- он и должен остаться
# остановленным, а не ожить сам собой; следующий раз он поднимется уже
# при следующем входе в Windows. Защита от "второй копии сторожа" --
# не в этой задаче, а в самом vigilar.py (файл data\vigilante.pid): даже
# если задачу запустить вручную поверх уже работающего сторожа, вторая
# копия сама увидит первую и тихо выйдет.

param(
    [string]$Nombre = "El Molino - Vigilante",
    # Имя старой (ежедневной) задачи -- если она осталась от прошлой
    # версии программы, эта задача больше не нужна и мешала бы путаницей
    # ("а какая из двух сейчас главная?"), поэтому убираем её здесь же.
    [string]$NombreViejo = "El Molino - autocarga",
    # Проверка: собрать задачу, но НЕ создавать её.
    [switch]$Probar
)

$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $carpeta "vigilante_oculto.vbs"

if (-not (Test-Path $vbs)) {
    Write-Host "ОШИБКА: рядом нет vigilante_oculto.vbs (искал: $vbs)" -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`"" -WorkingDirectory $carpeta
# -User ограничивает срабатывание входом именно ЭТОГО пользователя -- на
# компьютере с несколькими учётками сторож не будет пытаться запуститься
# под чужой.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($Probar) {
    Write-Host "Проверка: все части задачи собраны успешно." -ForegroundColor Green
    Write-Host "  запускать: wscript.exe `"$vbs`""
    Write-Host "  рабочая папка: $carpeta"
    Write-Host "  когда: при входе в Windows пользователя $env:USERNAME"
    Write-Host "  имя задачи: $Nombre"
    Write-Host ""
    Write-Host "(задача НЕ создана -- это была только проверка)"
    exit 0
}

# Старая ежедневная задача (если ставилась прошлой версией) -- убираем,
# чтобы не остались две разные автоматики одновременно.
if (Get-ScheduledTask -TaskName $NombreViejo -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $NombreViejo -Confirm:$false
    Write-Host "Старая ежедневная задача '$NombreViejo' убрана (заменена сторожем)."
}

Register-ScheduledTask -TaskName $Nombre -Action $action -Trigger $trigger `
    -Settings $settings -Description "Постоянный сторож El Molino: сам грузит новые выгрузки Wansoft" `
    -Force | Out-Null

# Не ждём следующего входа в Windows -- запускаем сразу же.
Start-ScheduledTask -TaskName $Nombre

Write-Host ""
Write-Host "Готово. Сторож поставлен в автозагрузку и уже запущен." -ForegroundColor Green
Write-Host "  задача: $Nombre"
Write-Host "  запускается сам при каждом входе в Windows, без единого окна"
Write-Host "  положил файл в отслеживаемую папку -- он в базе максимум через 15 секунд"
Write-Host ""
Write-Host "Проверить, что сторож действительно работает:"
Write-Host "  data\carga.log -- последняя строка должна быть 'сторож запущен'"
Write-Host "  data\vigilante.pid -- номер процесса, который сейчас следит"
Write-Host ""
Write-Host "Посмотреть его вживую (не мешая фоновому): двойной клик Vigilante.bat"
Write-Host "-- увидит, что фоновый уже работает, и сам сразу закроется."
Write-Host ""
Write-Host "Остановить совсем: Detener_Vigilante.bat"
