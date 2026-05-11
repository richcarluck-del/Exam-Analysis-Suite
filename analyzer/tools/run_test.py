import requests
import json

data = {
  "api_provider": "dashscope",
  "model_name": "qwen-vl-plus",
  "prompt_version": "v4",
  "input_dir": "D:\\10739\\Exam-Analysis-RAG\\data\\input",
  "output_dir": "",
  "mock_test": False
}

response = requests.post("http://127.0.0.1:5000/api/run_test", json=data)

print(response.json())
