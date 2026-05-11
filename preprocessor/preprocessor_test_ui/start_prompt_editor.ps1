# 提示词管理工具快速启动脚本 (PowerShell 版本)

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "提示词管理工具 - 快速启动" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. 安装前端依赖（如果需要）
Write-Host "[1/4] 检查前端依赖..." -ForegroundColor Yellow
Set-Location -Path ".\frontend"
if (-Not (Test-Path "node_modules")) {
    Write-Host "首次运行，正在安装依赖..." -ForegroundColor Green
    npm install
} else {
    Write-Host "依赖已安装，跳过" -ForegroundColor Green
}
Write-Host ""

# 2. 启动后端服务
Write-Host "[2/4] 启动后端服务..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    Set-Location ..
    python main.py
}
Write-Host "后端服务启动中..." -ForegroundColor Green
Start-Sleep -Seconds 3
Write-Host ""

# 3. 启动前端服务
Write-Host "[3/4] 启动前端服务..." -ForegroundColor Yellow
$frontendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    npm run dev
}
Write-Host "前端服务启动中..." -ForegroundColor Green
Start-Sleep -Seconds 3
Write-Host ""

# 4. 打开浏览器
Write-Host "[4/4] 打开浏览器..." -ForegroundColor Yellow
Start-Process "http://localhost:5173"
Write-Host ""

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "启动完成！" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "后端服务：http://localhost:8000 (后台运行)" -ForegroundColor White
Write-Host "前端服务：http://localhost:5173 (请查看终端输出的实际端口)" -ForegroundColor White
Write-Host ""
Write-Host "使用方法：" -ForegroundColor Yellow
Write-Host "1. 在浏览器中打开前端地址" -ForegroundColor White
Write-Host "2. 点击顶部工具栏的'提示词管理'按钮（✏️图标）" -ForegroundColor White
Write-Host "3. 即可查看、编辑和管理数据库中的提示词" -ForegroundColor White
Write-Host ""
Write-Host "按任意键退出此窗口..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
