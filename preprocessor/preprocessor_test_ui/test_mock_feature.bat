@echo off
echo ====================================
echo 测试 Mock 测试功能
echo ====================================
echo.

echo 步骤 1: 检查目录结构
echo -----------------------------------
if exist "D:\10739\Exam-Analysis-Suite\preprocessor\tests\mock_data" (
    echo [OK] tests/mock_data/ 目录存在
) else (
    echo [ERROR] tests/mock_data/ 目录不存在
)

if exist "D:\10739\Exam-Analysis-Suite\preprocessor\tests\test_cases" (
    echo [OK] tests/test_cases/ 目录存在
) else (
    echo [ERROR] tests/test_cases/ 目录不存在
)

echo.
echo 步骤 2: 检查前端构建
echo -----------------------------------
if exist "D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend\dist" (
    echo [OK] 前端已构建
) else (
    echo [ERROR] 前端未构建
)

echo.
echo 步骤 3: 启动测试 UI 服务
echo -----------------------------------
echo 请手动运行：cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui && python main.py
echo.
echo 然后访问 http://localhost:8001 测试以下功能：
echo 1. 录制测试 - 选择"录制测试"模式，输入 case 名称，运行测试
echo 2. 模拟测试 - 选择"模拟测试"模式，选择 mock case，勾选 mock 步骤，运行测试
echo 3. 真实测试 - 选择"真实测试"模式，运行测试（应该不受影响）
echo.

pause
