# 项目清理计划

## 目标
清理项目中冗余、临时、过时或无用的文件和目录，使项目结构更加清晰、专注和易于维护。

## 清理原则
- **保留核心逻辑**: `src/`, `question_solver/`, `vlm_e2e/` 内的代码是核心，需要保留。
- **保留测试资产**: `tests/mock_data/` 是项目的测试数据，必须保留。
- **保留配置文件**: `requirements.txt`, `.gitignore`, `docker-compose.yml`, `.env` 等配置文件需要保留。
- **删除临时产物**: 所有由程序运行产生的临时文件和输出目录都应被清理。
- **归档或删除杂项文件**: 根目录下的各种笔记、草稿、一次性脚本应被删除或归档到 `docs/` 目录。
- **审查实验性脚本**: `scripts/` 目录下的脚本需要逐一审查，删除不再需要的实验代码。

---

## 清理步骤

### 第一阶段：删除临时目录和缓存

这些目录包含了程序运行的中间产物或缓存，可以安全地完全删除。

- [ ] **删除 `temp/` 目录**: 包含所有 `run_*` 的临时工作区。
- [ ] **删除 `output/` 目录**: 包含历史的分析结果。
- [ ] **删除 `demo_output/` 目录**: 包含早期的演示输出。
- [ ] **删除 `vlm_e2e_output/` 目录**: 包含 `vlm_e2e` 模块的历史输出。
- [ ] **删除 `.ipynb_checkpoints/` 目录**: Jupyter Notebook 的缓存文件。

### 第二阶段：清理根目录下的杂乱文件

这些文件是一次性的测试、笔记或草稿，应予以删除。

- [ ] 删除 `greeting.txt`
- [ ] 删除 `index.html` (已被确认为无用的Vue.js示例)
- [ ] 删除 `new_gitignore.txt` (可能是 `.gitignore` 的草稿)
- [ ] 删除 `test.drawio` (设计图)
- [ ] 删除 `test.xmind` (思维导图)
- [ ] 删除 `test_output.txt` (临时测试输出)
- [ ] 删除 `testbuquan.py` (临时测试脚本)
- [ ] 删除 `visual_test.ipynb` (可视化测试的Notebook)
- [ ] 删除 `设计思路` (中文名的笔记文件)

### 第三阶段：审查并清理 `scripts/` 目录

`scripts/` 目录中包含了大量的实验性脚本，其中很多已经过时或功能冗余。

- [ ] **分析并删除以下脚本**:
    - `test_border.py`
    - `test_crop.py`
    - `test_detection_v2.py`
    - `test_detection_v3.py`
    - `test_detection_v4.py`
    - `test_ocr_detection.py`
    - `test_paddleocr_vl_siliconflow.py`
    - `test_question_detection_gemini.py`
    - `test_siliconflow_vlm.py`

### 第四阶段：最终确认和清理

- [ ] 在执行完以上所有删除操作后，最后再检查一遍项目结构。
- [ ] 移除 `main.py` 和 `.env` 文件中为了调试而添加的临时代码。
