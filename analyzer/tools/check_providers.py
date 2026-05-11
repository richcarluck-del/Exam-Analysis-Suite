#!/usr/bin/env python3
import requests

API_BASE = 'http://127.0.0.1:5000'

print("测试 API 供应商接口...")

# 测试 1：获取 providers
print("\n1. 测试 /api/providers")
try:
    response = requests.get(f'{API_BASE}/api/providers')
    print(f"   状态码：{response.status_code}")
    print(f"   响应：{response.json()}")
except Exception as e:
    print(f"   ❌ 错误：{e}")

# 测试 2：获取 prompt_lab
print("\n2. 测试 /api/prompt_lab")
try:
    response = requests.get(f'{API_BASE}/api/prompt_lab')
    print(f"   状态码：{response.status_code}")
    data = response.json()
    print(f"   提示词数量：{len(data)}")
    for p in data[:3]:
        print(f"     - {p['name']}: {p['description'][:50]}...")
except Exception as e:
    print(f"   ❌ 错误：{e}")
