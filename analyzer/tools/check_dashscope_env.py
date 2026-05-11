import os

api_key = os.environ.get("DASHSCOPE_API_KEY")

if api_key:
    print("DASHSCOPE_API_KEY 环境变量已成功获取。")
    print(f"密钥长度: {len(api_key)}")
else:
    print("DASHSCOPE_API_KEY 环境变量未设置或为空。")
