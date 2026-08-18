<#
.SYNOPSIS
  ResuAlign 一键恢复（Windows PowerShell 包装）。

.DESCRIPTION
  实际逻辑在 scripts/backup_restore.py：校验备份 manifest，把当前
  DB / uploads 移成 *.pre-restore-* 现场，再还原同一快照并清理陈旧
  -wal/-shm。要求服务已停止（默认检查 8000 端口，可用 -Force 跳过）。

.PARAMETER DataDir
  数据目录。默认 "data"，相对仓库根目录解析；也可传绝对路径。

.PARAMETER Manifest
  指定 manifest 文件；缺省自动选 backups/ 下最新一份。

.PARAMETER Force
  即使 8000 端口有服务监听也继续（仅在确实已停服时使用）。

.EXAMPLE
  powershell -File scripts/restore.ps1
  powershell -File scripts/restore.ps1 -DataDir "D:\resualign-data"
#>
param(
  [string]$DataDir = "",
  [string]$Manifest = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $Root
$Script = Join-Path $Root "backup_restore.py"

$Py = "python"
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) { $Py = "python3" }
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
  Write-Error "[restore] python not found"
  exit 1
}

$Args = @($Script, "restore")
if ($DataDir) { $Args += @("--data-dir", $DataDir) }
if ($Manifest) { $Args += @("--manifest", $Manifest) }
if ($Force) { $Args += @("--force") }

& $Py @Args
exit $LASTEXITCODE
