# ============================================================================
# blogitem — PyInstaller 단일 실행 파일 빌드
# ============================================================================
# 사용:
#   uv sync --extra build       # PyInstaller 설치
#   .\scripts\build_exe.ps1
# 산출물:
#   dist\blogitem.exe
# ----------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

Write-Host "[blogitem] PyInstaller 빌드 시작" -ForegroundColor Cyan

# 빌드 디렉토리 정리
if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
if (Test-Path .\dist)  { Remove-Item -Recurse -Force .\dist  }

uv run pyinstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name blogitem `
    --paths src `
    --collect-all PySide6 `
    --collect-all anthropic `
    --hidden-import keyring.backends.Windows `
    src\blogitem\__main__.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "[blogitem] 빌드 실패" -ForegroundColor Red
    exit 1
}

Write-Host "[blogitem] 빌드 완료 → dist\blogitem.exe" -ForegroundColor Green
