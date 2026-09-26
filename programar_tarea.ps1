# programar_tarea.ps1 -- ставит ежедневную загрузку в планировщик Windows.
# Запускается не сам по себе, а из Schedule.bat (двойной клик).
#
# Почему PowerShell, а не простая команда schtasks: нужна настройка
# "запустить, как только появится возможность" (StartWhenAvailable). Без
# неё пропущенный запуск просто теряется -- а он будет пропускаться
# постоянно: задача стоит на утро по Москве, и если компьютер в это время
# спит или выключен, загрузка за день не произойдёт вовсе. С этой
# настройкой Windows выполнит её при ближайшем включении.

param(
    # Время по часам ЭТОГО компьютера. 11:00 в Москве -- это около 02:00 в
    # Сан-Луис-Потоси: вчерашний день в пекарнях уже закрыт, и выгрузка за
    # него полная. Если запускать вечером по Москве, в Мексике будет
    # середина дня и в базу ляжет половина дня.
    [string]$Hora = "11:00",
    [string]$Nombre = "El Molino - autocarga",
    # Проверка: собрать задачу, но НЕ создавать её.
    [switch]$Probar
)

$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $carpeta "Autoload.bat"

if (-not (Test-Path $bat)) {
    Write-Host "ОШИБКА: рядом нет Autoload.bat (искал: $bat)" -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute $bat -Argument "--tarea" -WorkingDirectory $carpeta
$trigger = New-ScheduledTaskTrigger -Daily -At $Hora
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if ($Probar) {
    # Register-ScheduledTask -- команда из другого семейства (CIM) и
    # привычного -WhatIf не понимает, поэтому "пробный прогон" устроен
    # так: собираем все части задачи по-настоящему (тут и выяснится, если
    # где-то опечатка в параметрах или путь не найден), но саму
    # регистрацию не вызываем.
    Write-Host "Проверка: все части задачи собраны успешно." -ForegroundColor Green
    Write-Host "  запускать: $bat --tarea"
    Write-Host "  рабочая папка: $carpeta"
    # Показываем именно $Hora, а не trigger.StartBoundary: там время
    # хранится в UTC (для Москвы это на 3 часа меньше), и в отчёте о
    # проверке получалось бы "08:00" вместо заказанных 11:00.
    Write-Host "  расписание: ежедневно в $Hora по часам этого компьютера"
    Write-Host "  догонять пропущенное: $($settings.StartWhenAvailable)"
    Write-Host "  имя задачи: $Nombre"
    Write-Host ""
    Write-Host "(задача НЕ создана -- это была только проверка)"
    exit 0
}

Register-ScheduledTask -TaskName $Nombre -Action $action -Trigger $trigger `
    -Settings $settings -Description "Загрузка выгрузок Wansoft в базу El Molino" `
    -Force | Out-Null

Write-Host ""
Write-Host "Готово. Задача создана: $Nombre" -ForegroundColor Green
Write-Host "  запускается ежедневно в $Hora по времени этого компьютера"
Write-Host "  (это примерно 02:00 в Сан-Луис-Потоси -- вчерашний день уже закрыт)"
Write-Host "  если компьютер в это время выключен -- выполнится при включении"
Write-Host ""
Write-Host "Проверить прямо сейчас, не дожидаясь указанного времени:"
Write-Host "  Start-ScheduledTask -TaskName '$Nombre'"
Write-Host ""
Write-Host "Убрать задачу:"
Write-Host "  Unregister-ScheduledTask -TaskName '$Nombre' -Confirm:`$false"
Write-Host ""
Write-Host "Что происходило при каждом запуске -- видно в файле data\carga.log"
