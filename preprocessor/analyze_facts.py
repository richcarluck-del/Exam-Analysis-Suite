import json

print("=" * 80)
print("一、图片分类结果（来自 02_classify_output.json）")
print("=" * 80)

with open(r'D:\10739\Exam-Analysis-Suite\preprocessor\temp\run_20260324_142935\02_classify_output.json', 'r', encoding='utf-8') as f:
    classify_data = json.load(f)

print(f"\n共 {len(classify_data['sheets'])} 张图片：\n")

for sheet in classify_data['sheets']:
    original_image = sheet.get('original_image', '')
    filename = original_image.split('\\')[-1] if original_image else '未知'
    sheet_type = sheet.get('sheet_type', '未知')
    sheet_type_cn = sheet.get('sheet_type_cn', '未知')
    sheet_id = sheet.get('sheet_id', '未知')
    
    print(f"• {filename}")
    print(f"  - sheet_id: {sheet_id}")
    print(f"  - 类型: {sheet_type} ({sheet_type_cn})")

print("\n" + "=" * 80)
print("二、内容提取结果（来自 04_content_output.json）")
print("=" * 80)

with open(r'D:\10739\Exam-Analysis-Suite\preprocessor\temp\run_20260324_142935\04_content_output.json', 'r', encoding='utf-8') as f:
    content_data = json.load(f)

print(f"\n共 {len(content_data)} 个内容提取条目：\n")

all_questions = []
all_answers = []

for item in content_data:
    sheet_id = item.get('sheet_id', '未知')
    page_type = item.get('page_type', '未知')
    part = item.get('part', '未知')
    vlm_output = item.get('vlm_output', {})
    questions = vlm_output.get('questions', [])
    
    # 找到对应的图片文件名
    corrected_image = item.get('corrected_image', '')
    filename = corrected_image.split('\\')[-1] if corrected_image else '未知'
    
    print(f"• {filename} - {part} 部分")
    print(f"  - sheet_id: {sheet_id}")
    print(f"  - 页面类型: {page_type}")
    print(f"  - 识别出 {len(questions)} 个项目：")
    
    for q in questions:
        number = q.get('number', '?')
        text = q.get('text', q.get('description', ''))[:60]
        q_type = q.get('type', '未知')
        
        # 判断是题目还是答案区
        if '填涂' in text or '涂卡' in text or q_type == 'objective_choice':
            all_answers.append({
                'number': number,
                'text': text,
                'type': q_type,
                'sheet_id': sheet_id,
                'filename': filename
            })
            print(f"    [答案区] 题{number}: {text}... (type={q_type})")
        else:
            all_questions.append({
                'number': number,
                'text': text,
                'type': q_type,
                'sheet_id': sheet_id,
                'filename': filename
            })
            print(f"    [题目] 题{number}: {text}... (type={q_type})")
    
    print()

print("\n" + "=" * 80)
print("三、统计汇总")
print("=" * 80)

print(f"\n【题目统计】")
print(f"  共识别出 {len(all_questions)} 道题目")
print(f"  题号列表: {sorted([q['number'] for q in all_questions], key=lambda x: (len(str(x)), str(x)))}")

print(f"\n【答案区统计】")
print(f"  共识别出 {len(all_answers)} 个答案区")
print(f"  题号列表: {sorted([a['number'] for a in all_answers], key=lambda x: (len(str(x)), str(x)))}")

# 按图片分组统计
print(f"\n【按图片分组】")
for sheet in classify_data['sheets']:
    sheet_id = sheet['sheet_id']
    original_image = sheet.get('original_image', '')
    filename = original_image.split('\\')[-1] if original_image else '未知'
    
    q_count = len([q for q in all_questions if q['sheet_id'] == sheet_id])
    a_count = len([a for a in all_answers if a['sheet_id'] == sheet_id])
    
    print(f"  {filename}: {q_count} 道题目, {a_count} 个答案区")

print("\n" + "=" * 80)
print("四、完整单元（来自 complete_units.json）")
print("=" * 80)

with open(r'D:\10739\Exam-Analysis-Suite\preprocessor\temp\run_20260324_142935\complete_units.json', 'r', encoding='utf-8') as f:
    complete_units = json.load(f)

print(f"\n共 {len(complete_units)} 个完整单元：\n")

for q_num, unit in complete_units.items():
    question_text = unit.get('question_text', '无描述')[:50]
    answer = unit.get('answer', '无答案')
    answer_source = unit.get('answer_source', '未知')
    sheet_id = unit.get('sheet_id', '未知')
    question_slice = unit.get('question_slice_path')
    answer_slice = unit.get('answer_slice_path')
    complete_image = unit.get('complete_unit_image_path')
    
    print(f"题{q_num}:")
    print(f"  - 题目: {question_text}...")
    print(f"  - 答案: {answer} (来源: {answer_source})")
    print(f"  - sheet_id: {sheet_id}")
    print(f"  - 题目切片: {'有' if question_slice else '无'}")
    print(f"  - 答案切片: {'有' if answer_slice else '无'}")
    print(f"  - 完整单元图: {'有' if complete_image else '无'}")
    print()

print("=" * 80)
