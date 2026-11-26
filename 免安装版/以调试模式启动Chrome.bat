@echo off
chcp 65001 >nul
title 启动调试版 Chrome（供抓包工具附加）
setlocal EnableDelayedExpansion

set "PORT=9222"
set "PROFILE=%LOCALAPPDATA%\PacketCapChrome"

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo 没有找到 Chrome，请确认已安装谷歌浏览器。
  pause
  exit /b 1
)

if not exist "%PROFILE%" mkdir "%PROFILE%" >nul 2>&1

rem 按当前屏幕工作区计算窗口位置尺寸，保证窗口完整显示在屏幕内
set "WPOS="
for /f "usebackq tokens=1,2,3,4" %%A in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $w=[System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea; Write-Output ('{0} {1} {2} {3}' -f $w.X,$w.Y,$w.Width,$w.Height)"`) do (
  set /a "BW=%%C-80"
  if !BW! GTR 1180 set /a "BW=1180"
  if !BW! LSS 800 set /a "BW=800"
  set /a "BH=%%D-80"
  if !BH! GTR 760 set /a "BH=760"
  if !BH! LSS 560 set /a "BH=560"
  set /a "BX=%%A+40"
  set /a "BY=%%B+40"
  set "WPOS=--window-position=!BX!,!BY! --window-size=!BW!,!BH!"
)

echo 正在启动带调试端口的 Chrome ...
echo 调试端口: %PORT%
echo 专用配置目录: %PROFILE%
echo 窗口参数: %WPOS%
echo.
echo 说明：
echo  1. 这个 Chrome 用的是独立配置，第一次用请在这里登录你要抓的网站。
echo  2. 登录态会保存在这个目录里，下次启动不用重新登录。
echo  3. 启动后回到抓包工具，点「附加已开浏览器」，端口填 %PORT%。
echo  4. 抓完包点「停止抓包」，只会断开连接，不会关闭你的 Chrome。
echo.
start "" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check %WPOS% about:blank
timeout /t 2 >nul
echo 已完成。可以回到抓包工具点「附加已开浏览器」了。
timeout /t 6 >nul
