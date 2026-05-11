#!/usr/bin/env python3
import requests

API_BASE = 'http://127.0.0.1:5000'

print("检查 Test Run ID 24 的状态...")
response = requests.get(f'{API_BASE}/api/test_run/24')
if response.status_code == 200:
    result = response.json()
    print(f"状态：{result.get('overall_status', 'unknown')}")
    print(f"创建时间：{result.get('created_at')}")
    print(f"输出目录：{result.get('output_dir')}")
    print(f"备注：{result.get('notes')}")
    print(f"步骤范围：{result.get('start_step')} - {result.get('end_step')}")
else:
    print(f"获取失败：{response.status_code}")
    print(response.text)
