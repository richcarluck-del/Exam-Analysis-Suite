import json

with open('d:\\10739\\Exam-Analysis-Suite\\preprocessor\\tests\\mock_data\\case_1774181035132\\04_content_output.json', 'r', encoding='utf-8') as f:
    content = json.load(f)

print('=== 04_content_output.json 中的内容 ===')
for part in content:
    print(f"\n图片：{part.get('source_corrected_image', '')}")
    print(f"类型：{part.get('sheet_type', '')}")
    vlm_output = part.get('vlm_output', {})
    questions = vlm_output.get('questions', [])
    print(f'题目数：{len(questions)}')
    q_nums = [q.get('number') for q in questions]
    print(f'题号：{q_nums}')
