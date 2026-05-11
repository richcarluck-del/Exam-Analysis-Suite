#!/usr/bin/env python3
import requests

API_BASE = 'http://127.0.0.1:5000'

print("检查最新的实验区测试记录...")
response = requests.get(f'{API_BASE}/api/prompt_lab_tests')
if response.status_code == 200:
    tests = response.json()
    print(f"共有 {len(tests)} 条测试记录\n")
    
    if tests:
        latest = tests[0]
        print(f"最新测试记录：")
        print(f"  ID: {latest['id']}")
        print(f"  提示词 ID: {latest['prompt_lab_id']}")
        print(f"  供应商：{latest['provider_name']}")
        print(f"  模型：{latest['model_name']}")
        print(f"  输入数据：{latest['input_data'][:100] if latest['input_data'] else 'None'}...")
        print(f"  状态：{latest['status']}")
        print(f"  错误信息：{latest.get('error_message', 'None')}")
        print(f"  输出数据：{latest['output_data'][:200] if latest['output_data'] else 'None'}...")
        print(f"  创建时间：{latest['created_at']}")
    else:
        print("暂无测试记录")
else:
    print(f"获取失败：{response.status_code}")
    print(response.text)
