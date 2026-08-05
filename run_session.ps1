<#
run_session.ps1 — Claude Code を headless で起動して1セッション実行する（Windows 版）

    .\run_session.ps1 jp-open
    .\run_session.ps1 report

session.sh の中身をそのまま PowerShell に移したもの。タスクスケジューラから
呼ばれる想定で、ログは logs\ に残る。Linux/Mac なら session.sh を使うこと。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("jp-open", "jp-close", "us-open", "us-close", "report")]
    [string]$Session
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# この PC は python=3.11 / python3=3.13 と別物を指している。どちらで動かすか明示する。
$Python = "python"

# 日本語を含む出力が cp932 で化けないように固定する。
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# npm のグローバル bin が PATH に無い環境（タスクスケジューラ）でも動くようにする
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = Join-Path $env:APPDATA "npm\claude.cmd" }
if (-not (Test-Path $claude)) { throw "claude CLI が見つからない: $claude" }

# 日付は broker.py に合わせて JST で扱う（PC のタイムゾーンに依存させない）
$tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Tokyo Standard Time")
$nowJst = [System.TimeZoneInfo]::ConvertTimeFromUtc((Get-Date).ToUniversalTime(), $tz)
$stamp = $nowJst.ToString("yyyy-MM-dd_HHmm")
$today = $nowJst.ToString("yyyy-MM-dd")

New-Item -ItemType Directory -Force -Path "logs", "reports" | Out-Null
$log = Join-Path $PSScriptRoot "logs\$Session.log"

switch ($Session) {
    "jp-open" {
        $prompt = @"
日本株ブックの寄り付き後セッションです（--session jp-open）。
CLAUDE.md の手順に従ってください。前場の値動きと朝方のニュースを確認し、
保有の前提が崩れていないかを最優先で見てください。
"@
    }
    "jp-close" {
        $prompt = @"
日本株ブックの引け前セッションです（--session jp-close）。
CLAUDE.md の手順に従ってください。本日の値動きの理由を確認し、
翌日以降に持ち越すべきでないポジションがないか判断してください。
"@
    }
    "us-open" {
        $prompt = @"
米国株ブックの寄り付き後セッションです（--session us-open）。
CLAUDE.md の手順に従ってください。寄り付きの反応と前日引け後の決算・
ガイダンス発表を確認してください。
"@
    }
    "us-close" {
        $prompt = @"
米国株ブックの引け前セッションです（--session us-close）。
CLAUDE.md の手順に従ってください。本日の総括と、引け後に予定されている
イベント（決算発表など）への備えを判断してください。
"@
    }
    "report" {
        & $Python broker.py snapshot
        $prompt = @"
日報作成セッションです（--session report）。
broker.py status と broker.py journal --days 1 を実行し、CLAUDE.md の
「日報」の項に従って reports/$today.md を作成してください。
売買しなかった理由と、自分の判断の誤りについて必ず触れてください。
"@
    }
}

$header = "=== $Session @ $stamp ==="
Write-Output $header
$header | Out-File -FilePath $log -Append -Encoding utf8

& $claude -p $prompt `
    --allowedTools "Bash($Python broker.py:*)" "WebSearch" "WebFetch" "Read" "Write(reports/*)" |
    Tee-Object -Variable captured

$captured | Out-File -FilePath $log -Append -Encoding utf8
