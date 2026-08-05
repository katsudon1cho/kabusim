<#
register_tasks.ps1 — run_session.ps1 を Windows タスクスケジューラに登録する

    .\register_tasks.ps1            # 夏時間（3月〜11月）の時刻で登録
    .\register_tasks.ps1 -Winter    # 冬時間（11月〜3月）の時刻で登録し直す
    .\register_tasks.ps1 -Remove    # 登録を全部消す

米国市場は夏時間で1時間ずれるので、11月の切り替え時に -Winter で登録し直すこと。
忘れると us-open が開場前、us-close が引け後に走る。

登録される設定:
  -WakeToRun         スリープしていても PC を起こして実行する
  -StartWhenAvailable 実行し損ねた分を次回起動時に走らせる
PC の電源が完全に切れていると実行されない。確実にやるならスリープ無効で常時起動。
#>
[CmdletBinding()]
param(
    [switch]$Winter,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$tueToSat = @("Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

if ($Winter) {
    # 冬時間: 米国市場 23:30〜06:00 JST
    $usOpen = "23:45"; $usClose = "05:45"; $report = "07:00"
} else {
    # 夏時間: 米国市場 22:30〜05:00 JST
    $usOpen = "23:00"; $usClose = "04:45"; $report = "06:00"
}

$jobs = @(
    @{ Name = "kabusim-jp-open";  Session = "jp-open";  At = "09:15"; Days = $weekdays },
    @{ Name = "kabusim-jp-close"; Session = "jp-close"; At = "14:45"; Days = $weekdays },
    @{ Name = "kabusim-us-open";  Session = "us-open";  At = $usOpen; Days = $weekdays },
    @{ Name = "kabusim-us-close"; Session = "us-close"; At = $usClose; Days = $tueToSat },
    @{ Name = "kabusim-report";   Session = "report";   At = $report; Days = $tueToSat }
)

if ($Remove) {
    foreach ($j in $jobs) {
        try {
            Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false -ErrorAction Stop
            Write-Host "削除: $($j.Name)"
        } catch {
            Write-Host "見つからない（スキップ）: $($j.Name)"
        }
    }
    return
}

if (-not (Test-Path (Join-Path $dir "run_session.ps1"))) {
    throw "run_session.ps1 が同じフォルダに無い: $dir"
}

$psExe = (Get-Command powershell.exe).Source
$season = if ($Winter) { "冬時間" } else { "夏時間" }
Write-Host "登録先: $dir  （$season の時刻）"

foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $psExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$dir\run_session.ps1`" -Session $($j.Session)" `
        -WorkingDirectory $dir

    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $j.Days -At $j.At

    $settings = New-ScheduledTaskSettingsSet `
        -WakeToRun -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger `
        -Settings $settings -Force `
        -Description "kabusim 仮想運用エージェント: $($j.Session) セッション" | Out-Null

    Write-Host ("  {0,-20} {1}  {2}" -f $j.Name, $j.At, ($j.Days -join ","))
}

Write-Host ""
Write-Host "確認:  Get-ScheduledTask -TaskName 'kabusim-*' | Format-Table TaskName,State"
Write-Host "手動実行: Start-ScheduledTask -TaskName 'kabusim-jp-open'"
