#!/usr/bin/env python3
import requests

API_BASE = 'http://127.0.0.1:5000'

print("检查 Test Run ID 31 的状态...")
response = requests.get(f'{API_BASE}/api/test_run/31')
if response.status_code == 200:
    result = response.json()
    print(f"状态：{result.get('overall_status', 'unknown')}")
    print(f"创建时间：{result.get('created_at')}")
    print(f"输出目录：{result.get('output_dir')}")
    print(f"备注：{result.get('notes')}")
    
    # 检查日志文件
    import os
    output_dir = result.get('output_dir', '')
    if output_dir and os.path.exists(output_dir):
        log_file = os.path.join(output_dir, f'run_31.log')
        if os.path.exists(log_file):
            size = os.path.getsize(log_file)
            print(f"\n日志文件：run_31.log ({size} bytes)")
            
            # 读取最后几行
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                print(f"日志行数：{len(lines)}")
                if len(lines) > 0:
                    print(f"\n最后 5 行：")
                    for line in lines[-5:]:
                        print(line.strip())
        else:
            print(f"\n日志文件不存在")
else:
    print(f"获取失败：{response.status_code}")
    print(response.text)
