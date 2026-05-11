#!/usr/bin/env python3
import requests

API_BASE = 'http://127.0.0.1:5000'

print("检查 API 数据...")

# 检查 providers
print("\n1. GET /api/providers")
try:
    r = requests.get(f'{API_BASE}/api/providers')
    print(f"   状态码：{r.status_code}")
    data = r.json()
    print(f"   数据：{data}")
except Exception as e:
    print(f"   错误：{e}")

# 检查 models
print("\n2. GET /api/models/dashscope")
try:
    r = requests.get(f'{API_BASE}/api/models/dashscope')
    print(f"   状态码：{r.status_code}")
    data = r.json()
    print(f"   数据：{data}")
except Exception as e:
    print(f"   错误：{e}")

# 检查 prompt_lab
print("\n3. GET /api/prompt_lab")
try:
    r = requests.get(f'{API_BASE}/api/prompt_lab')
    print(f"   状态码：{r.status_code}")
    data = r.json()
    print(f"   数量：{len(data)}")
    for p in data[:3]:
        print(f"     - {p['name']}")
except Exception as e:
    print(f"   错误：{e}")
