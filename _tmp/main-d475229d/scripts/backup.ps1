<#
.SYNOPSIS
  ResuAlign SQLite 在线一致性备份（Windows PowerShell 包装）。

.DESCRIPTION
  实际逻辑在 scripts/backup_restore.py：对 jobs.db / content.db /
  content-cache.db 使用 sqlite3 .backup() API 做一致性快照，同时把
  <DataDir>/uploads/ 打进同一个备份，并写出 manifest。服务可保持运行。

.PARAMETER DataDir
  数据目录。默认 "data"，相对仓库根目录解析；也可传绝对路径。

.EXAMPLE
  powershell -File scripts/backup.ps1
  powershell -File scripts/backup.ps1 -DataDir "D:\resualign-data"
#>
param(
  [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root
$Script = Join-Path $Root "backup_restore.py"

$Py = "python"
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) { $Py = "python3" }
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
  Write-Error "[backup] python not found"
  exit 1
}

$Args = @($Script, "backup")
if ($DataDir) { $Args += @("--data-dir", $DataDir) }

& $Py @Args
exit $LASTEXITCODE
