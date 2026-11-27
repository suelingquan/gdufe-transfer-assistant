@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "APPURL=http://127.0.0.1:8000"

if not exist "%PY%" (
  echo [提示] 未检测到 .venv，正在首次安装后端依赖...
  where python >nul 2>&1
  if errorlevel 1 (
    echo [错误] 没有找到 python 命令。请先安装 Python 3.10 及以上版本，安装时勾选 Add Python to PATH。
    pause
    exit /b 1
  )
  python -m venv .venv
  if not exist "%PY%" (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
  "%PY%" -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

if not exist "backend\web\index.html" (
  echo [提示] 缺少前端构建产物 backend\web。
  echo        请依次执行下面三步，再重新双击本脚本：
  echo          1. cd frontend
  echo          2. npm install
  echo          3. npm run build
  echo        然后把 frontend\dist 里的内容复制到 backend\web。
  echo        或者直接用浏览器访问 README 里「在线使用」的地址。
  pause
  exit /b 1
)

rem 如果后端已经在跑，直接打开页面
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%APPURL%/api/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if !errorlevel! equ 0 (
  echo 后端已在运行，正在打开浏览器...
  start "" "%APPURL%"
  exit /b 0
)

echo 正在启动后端服务，请稍候...
start "广财转专业助手 - 后端服务" /min "%PY%" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
powershell -NoProfile -Command "for ($i = 0; $i -lt 60; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%APPURL%/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1" >nul 2>&1

if !errorlevel! equ 0 (
  echo 启动成功，正在打开浏览器：%APPURL%
  start "" "%APPURL%"
  echo.
  echo 提示：关掉本窗口不会停止服务。
  echo 要停止服务，请关闭任务栏里“广财转专业助手 - 后端服务”那个窗口。
  ping -n 6 127.0.0.1 >nul 2>&1
) else (
  echo [错误] 后端启动失败，请查看任务栏里的后端服务窗口。
  pause
  exit /b 1
)
