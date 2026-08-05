<#
.SYNOPSIS
  ResuAlign SQLite 在线一致性备份（Windows PowerShell）。

.DESCRIPTION
  使用 Python sqlite3 .backup() API 对数据目录下的三个 SQLite 库
  （jobs.db、content.db、content-cache.db，存在的才备份）做在线一致性备份，
  并对备份文件执行保留策略清理：
    - 日备份（文件名不含 weekly）：保留 7 天
    - 每月 1 号生成的备份（文件名含 weekly）：保留 30 天
  备份目录：<DataDir>/backups/。

  不要在服务运行时直接 Copy-Item 复制 .db 文件：库处于 WAL 模式时，
  直接复制会得到不一致的快照。请始终使用本脚本（sqlite3 .backup API），
  服务可以保持运行，备份是一致的。

.PARAMETER DataDir
  数据目录。默认 "data"，相对仓库根目录解析；也可传绝对路径。

.EXAMPLE
  powershell -File scripts/backup.ps1
  powershell -File scripts/backup.ps1 -DataDir "D:\resualign-data"
#>
param(
  [string]$DataDir = "data"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root

if ([System.IO.Path]::IsPathRooted($DataDir)) {
  $ResolvedDataDir = $DataDir
} else {
  $ResolvedDataDir = Join-Path $RepoRoot $DataDir
}
if (-not (Test-Path -LiteralPath $ResolvedDataDir -PathType Container)) {
  Write-Error "[backup] data directory not found: $ResolvedDataDir"
  exit 1
}

$Py = "python"
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) { $Py = "python3" }
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
  Write-Error "[backup] python not found (needed for the sqlite3 backup API)"
  exit 1
}

$BackupDir = Join-Path $ResolvedDataDir "backups"
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Prefix = if ((Get-Date).Day -eq 1) { "weekly-" } else { "" }

Write-Host "[backup] start: data dir=$ResolvedDataDir backup dir=$BackupDir"

# Python 片段：打开源库 -> .backup() 在线备份到目标库 -> PRAGMA integrity_check。
$PyBackup = @'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
print(dst.execute("PRAGMA integrity_check").fetchone()[0])
dst.close()
src.close()
'@

$ok = 0
$fail = 0
foreach ($db in @("jobs.db", "content.db", "content-cache.db")) {
  $srcPath = Join-Path $ResolvedDataDir $db
  if (-not (Test-Path -LiteralPath $srcPath -PathType Leaf)) {
    Write-Host "[backup] skip: $db not found"
    continue
  }
  $dstName = "$db-$Prefix$Timestamp.db"
  $dstPath = Join-Path $BackupDir $dstName
  $integrity = $PyBackup | & $Py - $srcPath $dstPath
  if ($LASTEXITCODE -ne 0 -or $integrity -ne "ok") {
    Write-Host "[backup] FAILED: $db -> $dstName (integrity=$integrity exit=$LASTEXITCODE)" -ForegroundColor Red
    if (Test-Path -LiteralPath $dstPath) { Remove-Item -LiteralPath $dstPath -Force }
    $fail++
  } else {
    $size = (Get-Item -LiteralPath $dstPath).Length
    Write-Host "[backup] ok: $db -> $dstName ($size bytes, integrity=$integrity)"
    $ok++
  }
}

# 保留策略：按文件名区分日备份与 weekly 备份，按修改时间清理。
$cutoffDaily = (Get-Date).AddDays(-7)
$cutoffWeekly = (Get-Date).AddDays(-30)
$removed = 0
Get-ChildItem -LiteralPath $BackupDir -Filter "*.db" -File | ForEach-Object {
  if ($_.Name -notmatch '-([0-9]{8}-[0-9]{6}|weekly-[0-9]{8}-[0-9]{6})\.db$') { return }
  if ($_.Name -match '-weekly-') {
    if ($_.LastWriteTime -lt $cutoffWeekly) { Remove-Item -LiteralPath $_.FullName -Force; $removed++ }
  } else {
    if ($_.LastWriteTime -lt $cutoffDaily) { Remove-Item -LiteralPath $_.FullName -Force; $removed++ }
  }
}
Write-Host "[backup] retention: removed $removed expired backup(s) (daily >7d, weekly >30d)"

if ($fail -gt 0) {
  Write-Host "[backup] FAILED: $fail database(s), $ok ok" -ForegroundColor Red
  exit 1
}
Write-Host "[backup] done: $ok database(s) backed up to $BackupDir"
