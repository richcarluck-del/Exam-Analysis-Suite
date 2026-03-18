# A/B 方案对比测试实施计划

##  项目背景

### 当前问题
- **方案 A（当前方案）**：A3 试卷切分成左右两个 A4，分别识别
  - 优点：图像分辨率高，注意力集中
  - 缺点：题号重复混淆，上下文割裂，工程复杂

- **方案 B（新方案）**：A3 试卷整体识别
  - 优点：保持完整性，避免重复混淆，流程简化
  - 缺点：可能需要压缩图像，注意力分散

### 目标
实现 A/B 方案可配置、可并行执行、可对比测试的完整功能。

---

## 🎯 核心设计原则

1. **非侵入式**：不影响现有代码的正常运行
2. **可配置**：通过参数或 UI 选择方案
3. **可对比**：能够同时运行两种方案并对比结果
4. **可扩展**：未来可以轻松添加更多方案

---

## 📦 实施方案

### 阶段一：后端架构设计

#### 1.1 修改 main.py 添加方案选择参数

**文件**: `preprocessor/main.py`

**修改内容**:
```python
# 添加命令行参数
parser.add_argument(
    '--a3-strategy',
    type=str,
    choices=['split', 'whole', 'both'],
    default='split',
    help='A3 试卷处理策略：split=分割成 A4(方案 A), whole=整体识别 (方案 B), both=并行对比'
)
```

**逻辑**:
- `split`（方案 A）：当前逻辑，A3 分割成左右两部分
- `whole`（方案 B）：新逻辑，A3 整体识别，不分割
- `both`（对比模式）：同时运行两种方案，输出对比结果

#### 1.2 修改 A3Splitter 支持两种模式

**文件**: `preprocessor/src/a3_splitter.py`

**修改内容**:
```python
class A3Splitter:
    def __init__(self, strategy='split'):
        """
        Args:
            strategy: 'split' | 'whole'
        """
        self.strategy = strategy
    
    def process_a3_page(self, image_path):
        """
        统一入口，根据策略决定处理方式
        
        Returns:
            - split 模式：[PagePart(left), PagePart(right)]
            - whole 模式：[PagePart(whole)]
        """
        if self.strategy == 'split':
            return self.split_a3_page(image_path)
        elif self.strategy == 'whole':
            return self.treat_as_whole(image_path)
        elif self.strategy == 'both':
            # 返回两种结果
            return {
                'split': self.split_a3_page(image_path),
                'whole': self.treat_as_whole(image_path)
            }
    
    def treat_as_whole(self, image_path):
        """将 A3 作为整体处理（不分割）"""
        with Image.open(image_path) as img:
            width, height = img.size
        return [
            PagePart(
                part_type='whole',
                image_path=image_path,
                crop_area=(0, 0, width, height)
            )
        ]
```

#### 1.3 修改布局分析任务支持策略参数

**文件**: `preprocessor/src/tasks/task_analyze_layout.py`

**修改内容**:
```python
def run_layout_analysis(
    classification_input_path: str, 
    output_path: str, 
    a3_strategy: str = 'split',  # 新增参数
    api_key: str = None, 
    model_name: str = None, 
    api_url: str = None, 
    image_path_manager=None
):
    """
    Args:
        a3_strategy: 'split' | 'whole' | 'both'
    """
    splitter = A3Splitter(strategy=a3_strategy)
    
    # 根据策略处理每个页面
    for page_info in pages_to_analyze:
        page_parts = splitter.process_a3_page(actual_image_path)
        
        if a3_strategy == 'both':
            # 并行处理两种方案
            self.process_split_mode(page_parts['split'], page_info)
            self.process_whole_mode(page_parts['whole'], page_info)
        else:
            # 单一模式
            self.process_single_mode(page_parts, page_info)
```

#### 1.4 修改内容提取任务支持不同模式

**文件**: `preprocessor/src/tasks/task_extract_content.py`

**修改内容**:
```python
def run_content_extraction(
    layout_input_path: str, 
    output_path: str, 
    prompts_dict: dict, 
    workspace_dir: str, 
    a3_strategy: str = 'split',  # 新增参数
    api_key: str = None, 
    model_name: str = None, 
    api_url: str = None, 
    image_path_manager=None
):
    """
    根据布局分析结果提取内容
    
    支持：
    - split 模式：处理 left/right 两个 part
    - whole 模式：处理 whole part
    - both 模式：同时处理两种，分别输出
    """
```

#### 1.5 创建对比结果生成器

**新文件**: `preprocessor/src/ab_comparison.py`

```python
"""
A/B 方案对比分析器
"""

class ABComparator:
    def __init__(self, output_dir):
        self.output_dir = output_dir
    
    def compare_results(self, split_result_path, whole_result_path):
        """
        对比两种方案的结果
        
        对比维度：
        1. 识别的题目数量
        2. 题目坐标的 IoU（Intersection over Union）
        3. 题号识别的准确性
        4. 处理时间
        5. Token 消耗
        """
        # 加载两种方案的结果
        split_results = self.load_results(split_result_path)
        whole_results = self.load_results(whole_result_path)
        
        # 生成对比报告
        comparison_report = {
            'split_mode': {
                'total_questions': len(split_results),
                'processing_time': split_results.get('processing_time'),
                'token_usage': split_results.get('token_usage'),
                'questions': split_results
            },
            'whole_mode': {
                'total_questions': len(whole_results),
                'processing_time': whole_results.get('processing_time'),
                'token_usage': whole_results.get('token_usage'),
                'questions': whole_results
            },
            'comparison': {
                'question_count_diff': abs(len(split_results) - len(whole_results)),
                'time_diff': split_results.get('processing_time') - whole_results.get('processing_time'),
                'token_diff': split_results.get('token_usage') - whole_results.get('token_usage'),
                'duplicate_issues': self.detect_duplicate_issues(split_results, whole_results),
                'coord_accuracy': self.compare_coordinates(split_results, whole_results)
            }
        }
        
        # 保存对比报告
        self.save_comparison_report(comparison_report)
        
        return comparison_report
    
    def detect_duplicate_issues(self, split_results, whole_results):
        """
        检测方案 A 中的题号重复问题
        """
        # 分析 split 结果中是否有重复的题号
        split_question_numbers = [q['number'] for q in split_results]
        duplicates = self.find_duplicates(split_question_numbers)
        
        return {
            'has_duplicates': len(duplicates) > 0,
            'duplicate_numbers': duplicates,
            'count': len(duplicates)
        }
    
    def compare_coordinates(self, split_results, whole_results):
        """
        对比两种方案的坐标识别差异
        """
        # 计算 IoU 等指标
        pass
    
    def save_comparison_report(self, report):
        """保存对比报告为 JSON 和 HTML"""
        # 保存 JSON
        json_path = os.path.join(self.output_dir, 'ab_comparison_report.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # 生成 HTML 可视化报告
        html_path = os.path.join(self.output_dir, 'ab_comparison_report.html')
        self.generate_html_report(report, html_path)
```

---

### 阶段二：前端 UI 改造

#### 2.1 添加 A/B 方案选择组件

**文件**: `preprocessor/preprocessor_test_ui/frontend/src/App.jsx`

**修改内容**:
```jsx
// 新增状态
const [a3Strategy, setA3Strategy] = useState('split'); // 'split' | 'whole' | 'both'

// 新增 UI 组件
<FormControl fullWidth margin="normal">
  <InputLabel>A3 试卷处理策略</InputLabel>
  <Select 
    value={a3Strategy} 
    label="A3 试卷处理策略" 
    onChange={e => setA3Strategy(e.target.value)}
  >
    <MenuItem value="split">
      <Box>
        <Typography variant="body2">📄 方案 A：分割成 A4</Typography>
        <Typography variant="caption" color="textSecondary">
          将 A3 试卷切成左右两部分，分别识别
        </Typography>
      </Box>
    </MenuItem>
    <MenuItem value="whole">
      <Box>
        <Typography variant="body2">📋 方案 B：整体识别</Typography>
        <Typography variant="caption" color="textSecondary">
          A3 试卷整体识别，保持完整性
        </Typography>
      </Box>
    </MenuItem>
    <MenuItem value="both">
      <Box>
        <Typography variant="body2">🔬 A/B 对比测试</Typography>
        <Typography variant="caption" color="textSecondary">
          同时运行两种方案，生成对比报告
        </Typography>
      </Box>
    </MenuItem>
  </Select>
</FormControl>

// 发送测试配置时添加策略参数
const config = {
  // ... 其他配置
  a3_strategy: a3Strategy,
};
```

#### 2.2 添加对比结果展示页面

**新文件**: `preprocessor/preprocessor_test_ui/frontend/src/ComparisonView.jsx`

```jsx
import React from 'react';
import { 
  Paper, Typography, Grid, Table, TableBody, 
  TableCell, TableContainer, TableHead, TableRow,
  Card, CardContent, Box, Chip
} from '@mui/material';

function ComparisonView({ comparisonData }) {
  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        📊 A/B 方案对比报告
      </Typography>
      
      {/* 核心指标对比 */}
      <Grid container spacing={3}>
        <Grid item xs={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                方案 A（分割）
              </Typography>
              <Typography variant="h4">
                {comparisonData.split_mode.total_questions}
              </Typography>
              <Typography variant="caption">
                识别题目数量
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                方案 B（整体）
              </Typography>
              <Typography variant="h4">
                {comparisonData.whole_mode.total_questions}
              </Typography>
              <Typography variant="caption">
                识别题目数量
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom>
                差异
              </Typography>
              <Typography variant="h4" color={
                comparisonData.comparison.question_count_diff === 0 
                  ? 'success.main' 
                  : 'warning.main'
              }>
                {comparisonData.comparison.question_count_diff === 0 
                  ? '✓ 一致' 
                  : `±${comparisonData.comparison.question_count_diff}`}
              </Typography>
              <Typography variant="caption">
                题目数量差异
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      
      {/* 详细对比表格 */}
      <TableContainer component={Paper} sx={{ mt: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>对比维度</TableCell>
              <TableCell>方案 A（分割）</TableCell>
              <TableCell>方案 B（整体）</TableCell>
              <TableCell>分析</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>识别题目数量</TableCell>
              <TableCell>{comparisonData.split_mode.total_questions}</TableCell>
              <TableCell>{comparisonData.whole_mode.total_questions}</TableCell>
              <TableCell>
                {comparisonData.split_mode.total_questions === comparisonData.whole_mode.total_questions
                  ? '✓ 两种方案识别的题目数量一致'
                  : '⚠ 数量不一致，需检查原因'}
              </TableCell>
            </TableRow>
            
            <TableRow>
              <TableCell>处理时间</TableCell>
              <TableCell>{comparisonData.split_mode.processing_time}s</TableCell>
              <TableCell>{comparisonData.whole_mode.processing_time}s</TableCell>
              <TableCell>
                {comparisonData.split_mode.processing_time > comparisonData.whole_mode.processing_time
                  ? '✓ 方案 B 更快'
                  : '⚠ 方案 A 更快'}
              </TableCell>
            </TableRow>
            
            <TableRow>
              <TableCell>Token 消耗</TableCell>
              <TableCell>{comparisonData.split_mode.token_usage}</TableCell>
              <TableCell>{comparisonData.whole_mode.token_usage}</TableCell>
              <TableCell>
                {comparisonData.split_mode.token_usage > comparisonData.whole_mode.token_usage
                  ? '✓ 方案 B 更节省'
                  : '⚠ 方案 A 更节省'}
              </TableCell>
            </TableRow>
            
            <TableRow>
              <TableCell>题号重复问题</TableCell>
              <TableCell>
                {comparisonData.comparison.duplicate_issues.has_duplicates ? (
                  <Chip label="存在重复" color="error" size="small" />
                ) : (
                  <Chip label="无重复" color="success" size="small" />
                )}
              </TableCell>
              <TableCell>-</TableCell>
              <TableCell>
                {comparisonData.comparison.duplicate_issues.has_duplicates && (
                  <Typography variant="caption" color="error">
                    发现 {comparisonData.comparison.duplicate_issues.count} 个重复题号：
                    {comparisonData.comparison.duplicate_issues.duplicate_numbers.join(', ')}
                  </Typography>
                )}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
      
      {/* 可视化对比 */}
      <Paper sx={{ p: 3, mt: 3 }}>
        <Typography variant="h6" gutterBottom>
          📈 坐标对比可视化
        </Typography>
        {/* 使用 Canvas 或 SVG 绘制两种方案的坐标对比 */}
      </Paper>
    </Box>
  );
}
```

#### 2.3 修改后端 API 支持对比结果查询

**文件**: `preprocessor/preprocessor_test_ui/main.py`

**修改内容**:
```python
# 新增 API 端点
@app.get("/api/comparison/{run_id}")
def get_comparison_result(run_id: str):
    """获取指定运行的 A/B 对比结果"""
    comparison_path = f"temp/{run_id}/ab_comparison_report.json"
    if os.path.exists(comparison_path):
        with open(comparison_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"error": "Comparison result not found"}

@app.get("/api/comparison/{run_id}/html")
def get_comparison_html(run_id: str):
    """获取对比报告的 HTML 页面"""
    html_path = f"temp/{run_id}/ab_comparison_report.html"
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"error": "HTML report not found"}
```

---

### 阶段三：测试与验证

#### 3.1 单元测试

**文件**: `preprocessor/tests/test_ab_comparison.py`

```python
"""
A/B 方案对比测试
"""

def test_split_mode():
    """测试方案 A（分割模式）"""
    # 使用 A3 试卷测试
    # 验证：
    # 1. 正确分割成左右两部分
    # 2. 每部分都正确识别题目
    # 3. 坐标转换正确

def test_whole_mode():
    """测试方案 B（整体模式）"""
    # 使用 A3 试卷测试
    # 验证：
    # 1. 不分割，整体识别
    # 2. 正确识别所有题目
    # 3. 坐标准确

def test_comparison_accuracy():
    """测试对比分析的准确性"""
    # 使用已知结果的测试数据
    # 验证对比报告正确识别差异
```

#### 3.2 集成测试

**测试数据集**:
- 准备 10 张典型 A3 试卷
- 包含不同题型、布局、难度
- 人工标注标准答案（题目数量、坐标）

**测试流程**:
1. 分别运行方案 A 和方案 B
2. 生成对比报告
3. 与人工标注对比
4. 计算准确率、召回率

#### 3.3 性能测试

**测试指标**:
- 处理时间
- Token 消耗
- 内存使用
- 准确率

---

## 📊 方案对比分析

### 大模型调用次数对比

**方案 A（切分方案）**：
- 步骤 1（透视矫正）：1 次调用
- 步骤 2（页面分类）：1 次调用
- 步骤 4（内容提取）：**2 次调用**（left + right 各 1 次）
- **总计：4 次调用**

**方案 B（整体方案）**：
- 步骤 1（透视矫正）：1 次调用
- 步骤 2（页面分类）：1 次调用
- 步骤 4（内容提取）：**1 次调用**（整体识别）
- **总计：3 次调用** ✅

**方案 B 优势**：
- ✅ 少 1 次大模型调用
- ✅ 节省 Token（少发送一张图片的 base64）
- ✅ 节省时间（少一次 API 调用）
- ✅ 降低成本（如果按调用次数计费）

---

## 📁 目录结构设计
```
temp/run_20260316_184328/
├── 00_preprocess_output.json
├── 01_correction_output.json
├── 02_classify_output.json
├── 03_layout_output.json          # 包含 left/right 两个 part
├── 04_content_output.json          # 分别识别 left/right
├── 05_merged_output.json
├── 06_final_output/
├── corrected_images/
│   ├── 1_corrected.jpg
│   ├── 1_corrected_left.jpg       # A 方案特有
│   └── 1_corrected_right.jpg      # A 方案特有
└── compressed_images/
```

### 方案 B（整体识别方案）- 兼容结构
```
temp/run_20260316_184328/
├── 00_preprocess_output.json
├── 01_correction_output.json
├── 02_classify_output.json
├── 03_layout_output.json          # 只包含 whole part
├── 04_content_output.json          # 整体识别
├── 05_merged_output.json
├── 06_final_output/
├── corrected_images/
│   └── 1_corrected.jpg            # 没有 left/right 分割
└── compressed_images/
```

**关键差异**：
- ✅ 目录结构完全相同（都在 temp 下创建新目录）
- ✅ 文件命名规则相同（03_layout_output.json 等）
- ✅ JSON 结构兼容（part_type: 'whole' vs 'left/right'）
- ⚠️ B 方案没有分割图片（`*_left.jpg` / `*_right.jpg`）

### 对比模式（both）- 并行执行
```
temp/run_20260316_184328/
├── 03_layout_output_split.json     # A 方案结果
├── 03_layout_output_whole.json     # B 方案结果
├── 04_content_output_split.json    # A 方案结果
├── 04_content_output_whole.json    # B 方案结果
├── 05_merged_output_split.json
├── 05_merged_output_whole.json
├── 06_final_output_split/
├── 06_final_output_whole/
├── ab_comparison_report.json       # 对比报告
├── ab_comparison_report.html
└── corrected_images/
    ├── 1_corrected.jpg
    ├── 1_corrected_left.jpg        # A 方案需要
    ├── 1_corrected_right.jpg       # A 方案需要
    └── 1_corrected_whole.jpg       # B 方案（可选）
```

---

## 📅 实施计划

### 第一阶段：后端核心功能（预计 2-3 小时）

1. ✅ 修改 `main.py` 添加 `--a3-strategy` 参数
2. ✅ 修改 `A3Splitter` 支持两种模式（保持向后兼容）
3. ✅ 修改 `task_analyze_layout.py` 支持策略参数
4. ✅ 修改 `task_extract_content.py` 支持策略参数
5. ✅ 创建 `ABComparator` 对比分析器

### 第二阶段：前端 UI（预计 2-3 小时）

1. ✅ 添加 A/B 方案选择下拉框
2. ✅ 修改测试配置发送逻辑
3. ✅ 创建对比结果展示页面
4. ✅ 添加对比结果 API 端点

### 第三阶段：测试验证（预计 1-2 小时）

1. ✅ 单元测试
2. ✅ 集成测试
3. ✅ 性能测试
4. ✅ 文档编写

### 第四阶段：优化完善（预计 1 小时）

1. ✅ 根据测试结果优化
2. ✅ 添加更多对比维度
3. ✅ 改进可视化效果

---

## 📊 预期输出

### 1. 代码输出
- ✅ 支持 A/B 方案的后端代码
- ✅ 支持 A/B 选择的前端界面
- ✅ 对比分析器和可视化报告

### 2. 测试输出
- ✅ 10 张 A3 试卷的对比测试结果
- ✅ 性能对比数据
- ✅ 准确率对比数据

### 3. 文档输出
- ✅ A/B 测试使用指南
- ✅ 对比分析报告模板
- ✅ 最佳实践建议

---

## 🎯 成功标准

1. **功能完整**：三种模式（split/whole/both）都能正常运行
2. **结果准确**：对比报告能准确识别两种方案的差异
3. **界面友好**：用户可以轻松选择方案并查看对比结果
4. **性能稳定**：不会因并行执行导致系统崩溃或内存溢出

---

## 🔍 关键技术点

### 1. 并行执行策略

**方案一：顺序执行**
```python
# 先执行方案 A
result_a = run_pipeline(strategy='split')
# 再执行方案 B
result_b = run_pipeline(strategy='whole')
# 对比
compare(result_a, result_b)
```

**方案二：并发执行**
```python
# 使用 asyncio 并发执行
result_a, result_b = await asyncio.gather(
    run_pipeline_async(strategy='split'),
    run_pipeline_async(strategy='whole')
)
compare(result_a, result_b)
```

**推荐**：方案一（顺序执行），更稳定，易于调试。

### 2. 结果对齐问题

**挑战**：两种方案识别的题目数量可能不同，如何对比？

**解决方案**：
- 使用题号 + 坐标双重匹配
- 允许一定的坐标误差（IoU > 0.8 视为同一题）
- 对于无法匹配的题目，标记为"额外识别"或"漏识别"

### 3. 可视化对比

**技术方案**：
- 使用 SVG 或 Canvas 绘制原图
- 在图上用不同颜色绘制两种方案的识别框
- 点击题目可以查看详细信息

---

## 📝 总结

本计划旨在实现一个完整、可靠、易用的 A/B 方案对比测试系统，帮助验证哪种 A3 试卷处理策略更优。通过系统化的对比分析，为最终的技术选型提供数据支持。

**核心优势**：
1. ✅ 非侵入式设计，不影响现有功能
2. ✅ 一键切换，操作简便
3. ✅ 自动化对比，减少人工分析
4. ✅ 可视化报告，直观易懂

**预期收益**：
- 明确两种方案的优劣势
- 量化性能差异
- 为后续优化提供方向
