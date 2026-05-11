@echo off
REM 提示词管理工具快速启动脚本

echo ================================================================================
echo 提示词管理工具 - 快速启动
echo ================================================================================
echo.

REM 1. 安装前端依赖（如果需要）
echo [1/4] 检查前端依赖...
cd frontend
if not exist node_modules (
    echo 首次运行，正在安装依赖...
    call npm install
) else (
    echo 依赖已安装，跳过
)
echo.

REM 2. 启动后端服务
echo [2/4] 启动后端服务...
start "提示词管理 - 后端" cmd /k "cd .. && python main.py"
echo 后端服务启动中...
timeout /t 3 /nobreak >nul
echo.

REM 3. 启动前端服务
echo [3/4] 启动前端服务...
start "提示词管理 - 前端" cmd /k "cd frontend && npm run dev"
echo 前端服务启动中...
timeout /t 3 /nobreak >nul
echo.

REM 4. 打开浏览器
echo [4/4] 打开浏览器...
start http://localhost:5173
echo.

echo ================================================================================
echo 启动完成！
echo ================================================================================
echo.
echo 后端服务：http://localhost:8000
echo 前端服务：http://localhost:5173（请查看终端输出的实际端口）
echo.
echo 使用方法：
echo 1. 在浏览器中打开前端地址
echo 2. 点击顶部工具栏的"提示词管理"按钮（✏️图标）
echo 3. 即可查看、编辑和管理数据库中的提示词
echo.
echo 按任意键退出此窗口...
pause >nul
