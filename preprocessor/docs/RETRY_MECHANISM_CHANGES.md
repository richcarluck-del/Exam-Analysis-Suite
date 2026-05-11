# 大模型调用重试机制增强

## 修改概述

为所有调用大模型的环节添加了**空结果判断**和**少字数判断**的重试机制，确保大模型返回有效内容。

## 核心修改

### 1. **api_utils.py** - 核心 API 调用函数

**文件路径**: `src/utils/api_utils.py`

**修改内容**:
- ✅ 新增 `min_content_length` 参数（默认 10 个字符）
- ✅ 在 API 返回后检查内容是否为空
- ✅ 在 API 返回后检查内容字数是否少于 `min_content_length`
- ✅ 如果为空或字数过少，抛出异常触发重试
- ✅ 增加结果长度打印日志

**代码变更**:
```python
def call_api(prompt: str, api_url: str, api_key: str, model_name: str, 
             image_path: str = None, retries: int = 5, logger=None, 
             step_name: str = "unknown", min_content_length: int = 10) -> str:
    """
    调用大模型 API，包含重试机制
    
    新增参数:
        min_content_length: 最小内容长度（默认 10 个字符，少于这个长度会重试）
    """
    # ... 省略 API 调用逻辑 ...
    
    # 检查返回内容是否为空或字数过少
    result_content_stripped = result_content.strip()
    if not result_content_stripped:
        raise Exception(f"API 返回空结果")
    
    if len(result_content_stripped) < min_content_length:
        raise Exception(f"API 返回内容字数过少（{len(result_content_stripped)} 字 < {min_content_length} 字要求）")
    
    print(f"  [出参结果]: {result_content_stripped}")
    print(f"  [结果长度]: {len(result_content_stripped)} 字符")
```

---

### 2. **utils.py** - 备用 API 调用函数

**文件路径**: `src/utils.py`

**修改内容**:
- ✅ 与 `api_utils.py` 相同的修改
- ✅ 新增 `min_content_length` 参数
- ✅ 添加空结果和少字数判断

---

### 3. **task_perspective_correction.py** - 透视矫正

**文件路径**: `src/tasks/task_perspective_correction.py`

**修改内容**:
- ✅ 调用 `call_api` 时设置 `min_content_length=50`
- ✅ 透视矫正需要返回 JSON 格式，设置较高的最小长度
- ✅ 保留原有的双重检查逻辑

**代码变更**:
```python
content = call_api(
    prompt=self.prompt, 
    image_path=image_path, 
    api_url=api_url, 
    api_key=api_key, 
    model_name=model_name,
    logger=logger,
    step_name="perspective_correction",
    min_content_length=50  # 透视矫正需要返回 JSON，设置较高的最小长度
)
```

---

### 4. **classifier.py** - 页面分类

**文件路径**: `src/classifier.py`

**修改内容**:
- ✅ 新增 `max_retries` 参数（默认 3 次）
- ✅ 添加重试循环逻辑
- ✅ 调用 `call_api` 时设置 `min_content_length=30`
- ✅ 打印重试日志
- ✅ 所有重试失败后使用默认类型 'other'

**代码变更**:
```python
def classify(self, image_paths: List[str] | str, api_key: str, 
             model_name: str, api_url: str, logger=None, 
             max_retries: int = 3) -> List[ExamPage] | ExamPage:
    
    # 重试循环
    while attempt < max_retries:
        attempt += 1
        
        if attempt == 1:
            print(f"  [尝试] 第 1 次调用分类 {os.path.basename(path)}（共{max_retries}次机会）")
        else:
            print(f"  [重试] 第 {attempt} 次重试分类 {os.path.basename(path)}（共{max_retries}次机会）")
        
        try:
            content = call_api(
                prompt=prompt,
                image_path=path,
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                logger=logger,
                step_name="page_classification",
                min_content_length=30  # 分类结果需要 JSON，设置适中的最小长度
            )
            break  # 成功则跳出重试循环
        except Exception as e:
            if attempt < max_retries:
                print(f"  [警告] 第 {attempt} 次调用失败：{e}，准备重试...")
            else:
                print(f"  [错误] 已达最大重试次数 ({max_retries})，分类失败：{e}")
                content = None
```

---

### 5. **task_long_image_classification.py** - 长图分类

**文件路径**: `src/tasks/task_long_image_classification.py`

**修改内容**:
- ✅ 添加重试循环逻辑（max_retries=3）
- ✅ 调用 `call_api` 时设置 `min_content_length=100`
- ✅ 长图分类需要返回多个结果，设置较高的最小长度
- ✅ 打印重试日志
- ✅ 所有重试失败后抛出异常

**代码变更**:
```python
# 重试逻辑
max_retries = 3
api_response = None
attempt = 0

while attempt < max_retries:
    attempt += 1
    
    if attempt == 1:
        print(f"  [尝试] 第 1 次调用长图分类（共{max_retries}次机会）")
    else:
        print(f"  [重试] 第 {attempt} 次重试长图分类（共{max_retries}次机会）")
    
    try:
        api_response = call_api(
            prompt=prompt,
            image_path=stitched_image_path,
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            logger=logger,
            step_name="long_image_classification",
            min_content_length=100  # 长图分类需要返回多个结果，设置较高的最小长度
        )
        print(f"  [成功] 第 {attempt} 次调用成功")
        break
    except Exception as e:
        if attempt < max_retries:
            print(f"  [警告] 第 {attempt} 次调用失败：{e}，准备重试...")
        else:
            print(f"  [错误] 已达最大重试次数 ({max_retries})，长图分类失败：{e}")
            raise
```

---

### 6. **task_extract_content.py** - 内容提取

**文件路径**: `src/tasks/task_extract_content.py`

**修改内容**:
- ✅ 添加重试循环逻辑（max_retries=3）
- ✅ 调用 `call_api` 时设置 `min_content_length=20`
- ✅ 内容提取需要返回题目，设置较低的最小长度
- ✅ 打印重试日志
- ✅ 所有重试失败后返回错误信息

**代码变更**:
```python
# 重试逻辑
max_retries = 3
attempt = 0
api_response = None
extracted_data = None

while attempt < max_retries:
    attempt += 1
    
    if attempt == 1:
        print(f"      [尝试] 第 1 次调用内容提取 {part_basename}（共{max_retries}次机会）")
    else:
        print(f"      [重试] 第 {attempt} 次重试内容提取 {part_basename}（共{max_retries}次机会）")
    
    try:
        api_response = call_api(
            prompt=prompt, 
            image_path=actual_part_image_path,
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            logger=logger,
            step_name=f"content_extraction_{page_type}",
            min_content_length=20  # 内容提取需要返回题目，设置较低的最小长度
        )
        break
    except Exception as api_error:
        if attempt < max_retries:
            print(f"      [警告] 第 {attempt} 次调用失败：{api_error}，准备重试...")
            api_response = None
        else:
            print(f"      [错误] 已达最大重试次数 ({max_retries})，内容提取失败：{api_error}")
            extracted_data = {"questions": [], "error": str(api_error)}
```

---

### 7. **vlm_recognizer.py** - 涂卡识别

**文件路径**: `src/answer_card/vlm_recognizer.py`

**修改内容**:
- ✅ 添加重试循环逻辑（max_retries=3）
- ✅ 调用 `call_api` 时设置 `min_content_length=15`
- ✅ 涂卡识别需要返回 JSON，设置较低的最小长度
- ✅ 打印重试日志
- ✅ 所有重试失败后返回空字典

**代码变更**:
```python
# 重试逻辑
max_retries = 3
response = None
attempt = 0

while attempt < max_retries:
    attempt += 1
    
    if attempt == 1:
        print(f"  [VLM 识别] 第 1 次调用涂卡识别（共{max_retries}次机会）")
    else:
        print(f"  [VLM 识别] 第 {attempt} 次重试涂卡识别（共{max_retries}次机会）")
    
    try:
        response = call_api(
            prompt=prompt,
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            image_path=crop_image_path,
            step_name="answer_card_vlm_recognition",
            min_content_length=15  # 涂卡识别需要返回 JSON，设置较低的最小长度
        )
        print(f"  [VLM 识别] 第 {attempt} 次调用成功，API 返回内容长度：{len(response)}")
        break
    except Exception as api_error:
        if attempt < max_retries:
            print(f"  [VLM 识别] 第 {attempt} 次调用失败：{api_error}，准备重试...")
        else:
            print(f"  [VLM 识别] 已达最大重试次数 ({max_retries})，涂卡识别失败：{api_error}")
            return {}
```

---

## 重试机制的工作原理

### 两级重试机制

```
┌─────────────────────────────────────┐
│  业务层重试（max_retries=3）          │
│  - classifier.py                    │
│  - task_long_image_classification.py │
│  - task_extract_content.py          │
│  - vlm_recognizer.py                │
└──────────────┬──────────────────────┘
               │
               ↓
┌─────────────────────────────────────┐
│  API 层重试（retries=5）               │
│  - api_utils.py / utils.py          │
│  - 429 限流自动重试                   │
│  - 空结果自动重试                     │
│  - 少字数自动重试                     │
└──────────────┬──────────────────────┘
               │
               ↓
        调用大模型 API
```

### 重试触发条件

1. **HTTP 429 限流** - API 层自动重试，等待时间指数增长
2. **API 返回空结果** - API 层抛出异常，触发业务层重试
3. **API 返回字数过少** - API 层抛出异常，触发业务层重试
4. **网络异常** - API 层抛出异常，触发业务层重试
5. **JSON 解析失败** - 业务层自行处理

### 最小内容长度设置

| 步骤 | 最小长度 | 原因 |
|------|---------|------|
| 透视矫正 | 50 字符 | 需要返回完整的 JSON 格式角点坐标 |
| 长图分类 | 100 字符 | 需要返回多个页面的分类结果 |
| 页面分类 | 30 字符 | 需要返回单个页面的 JSON 分类 |
| 内容提取 | 20 字符 | 需要返回题目识别结果 |
| 涂卡识别 | 15 字符 | 需要返回 JSON 格式的答案 |
| 默认值 | 10 字符 | 通用场景 |

---

## 日志输出示例

### 成功调用
```
>>>> [大模型 API 调用中] <<<<
  [API URL]: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
  [模型名称]: qwen3.5-plus
  [步骤名称]: page_classification
  [入参图片]: /path/to/image.jpg
  [入参 Prompt]: 请判断这张图片是否是一张**试卷**...
  [最小内容长度]: 30
--------------------------------
[DEBUG] is_volcengine: False
[DEBUG] api_url: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
  [Temperature]: 0.1
  [Seed]: 123456
  [Max Tokens]: 4000
--------------------------------
  [出参结果]: {"is_exam_paper": true, "page_type": "question_paper"}
  [结果长度]: 65 字符
<<<< [API 调用完成] >>>>
```

### 重试调用
```
  [尝试] 第 1 次调用分类 1.jpg（共 3 次机会）
>>>> [大模型 API 调用中] <<<<
  ...
  [出参结果]: OK
  [结果长度]: 2 字符
<<<< [API 调用完成] >>>>
  [警告] 第 1 次调用失败：API 返回内容字数过少（2 字 < 30 字要求），准备重试...
  [重试] 第 2 次重试分类 1.jpg（共 3 次机会）
...
  [成功] 第 2 次调用成功
```

---

## 修改文件清单

| 文件路径 | 修改类型 | 说明 |
|---------|---------|------|
| `src/utils/api_utils.py` | ✅ 修改 | 核心 API 调用函数，添加空结果和少字数判断 |
| `src/utils.py` | ✅ 修改 | 备用 API 调用函数，相同修改 |
| `src/tasks/task_perspective_correction.py` | ✅ 修改 | 透视矫正，设置 min_content_length=50 |
| `src/classifier.py` | ✅ 修改 | 页面分类，添加完整重试循环 |
| `src/tasks/task_long_image_classification.py` | ✅ 修改 | 长图分类，添加完整重试循环 |
| `src/tasks/task_extract_content.py` | ✅ 修改 | 内容提取，添加完整重试循环 |
| `src/answer_card/vlm_recognizer.py` | ✅ 修改 | 涂卡识别，添加完整重试循环 |

**总计**: 7 个文件被修改

---

## 测试建议

1. **单元测试**: 模拟 API 返回空结果和少字数的场景
2. **集成测试**: 使用真实 API 测试重试机制
3. **压力测试**: 模拟 API 限流场景
4. **日志验证**: 检查重试日志是否正确输出

---

## 版本信息

- **修改日期**: 2026-03-24
- **版本**: v0.4.1 (待发布)
- **修改内容**: 增强大模型调用重试机制
