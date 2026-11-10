# Registra (o actualiza) la tarea diaria de ingesta para el usuario actual.
#   powershell -ExecutionPolicy Bypass -File scripts\programar_ingesta.ps1 -Hora 12:00
# Quitarla:  Unregister-ScheduledTask -TaskName "CompradorInteligente-Ingesta" -Confirm:$false
param(
    [string]$Hora = "12:00",
    [string]$Nombre = "CompradorInteligente-Ingesta"
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "ingesta_diaria.cmd"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$script`"`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Hora
# StartWhenAvailable: si el equipo estaba apagado a esa hora, corre al encenderlo.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Nombre -Action $action -Trigger $trigger -Settings $settings `
    -Description "Comprador Inteligente: ingesta diaria de precios" -Force | Out-Null
Get-ScheduledTask -TaskName $Nombre | Select-Object TaskName, State
