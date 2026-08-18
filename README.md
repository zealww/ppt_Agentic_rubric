# PPT Eval 1

一个以“Rubric 配置优先”为核心的可维护 PPT 主观评估项目，支持整套文本、整套视觉和
逐页视觉三种评分输入。输入只需要是一个直接存放 `.ppt`/`.pptx` 的目录。

## 处理流程

```text
PPT → LibreOffice PDF → PyMuPDF PNG
                         ├─ 单页 VLM 内容提取 → extracted_text Rubric
                         ├─ 4页网格图          → slide_images Rubric
                         └─ 每页原始图片        → single_slide Rubric
                                      ↓
                         统一校验、加权、JSON报告
```

默认评分口径与此前 `my_ppt_eval` 保持一致：

- Content / Visual Design / Layout / Complexity；
- 权重为 30% / 30% / 20% / 20%；
- 相同子项权重与 0–10 整数评分；
- 4 页一张网格，默认最多 8 张；
- 文件名作为默认 topic；
- OpenAI-compatible Chat Completions 接口；
- 缓存渲染图片、提取文本与网格；
- 清理 Gemini 意外返回的 Base64 图片；
- 非法/不完整 JSON 自动重试并保留原始回复；
- 每评估完一份 PPT 立即写检查点，支持 `--resume`。
- 每个一级指标的每个子分都输出具体 `score_explanations`。
- `single_slide` 输出每一页的分数、子分和逐项解释。

## 项目结构

```text
pujiang_ppt_eval/
├── pujiang_ppt_eval/
│   ├── cli.py          # 参数解析和批量运行
│   ├── domain.py       # 不可变领域对象/运行配置
│   ├── evaluator.py    # 只负责流程编排
│   ├── extraction.py   # VLM 单页内容提取和缓存
│   ├── model.py        # OpenAI-compatible 模型适配器
│   ├── parsing.py      # JSON解析、结构校验、Base64清理
│   ├── preprocess.py   # PPT渲染和网格生成
│   ├── prompts.py      # 根据Rubric自动生成提示词/JSON结构
│   ├── reporting.py    # 检查点、汇总和结果文件
│   ├── rubric.py       # Rubric读取、验证和通用加权
│   ├── topics.py       # topic映射
│   └── rubrics/default.json
├── tests/test_core.py
├── topic_map.example.json
├── requirements.txt
└── pyproject.toml
```

## 安装

```bash
cd /mnt/shared-storage-gpfs2/intern-pretrain-shared02/liuyanjiang/liushuainan/ppt_eval_1
conda activate ppt_eval
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 中配置：

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://your-compatible-endpoint/v1
```

## 运行（原四类整套评分）

```bash
python -m pujiang_ppt_eval \
  --source /mnt/shared-storage-gpfs2/intern-pretrain-shared02/liuyanjiang/liushuainan/ppt_dataset/good \
  --output ./output/gemini_good \
  --model gemini-2.5-flash-image \
  --workers 2 \
  --result-file results.json
```

## Web 前端

启动服务：

```bash
cd /mnt/shared-storage-gpfs2/intern-pretrain-shared02/liuyanjiang/liushuainan/ppt_eval_1
conda activate ppt_eval
python -m pujiang_ppt_eval.web --host 0.0.0.0 --port 7860
```

浏览器访问 `http://服务器地址:7860`；同一台机器上可以使用
`http://127.0.0.1:7860`。

页面支持：

- 拖拽或多选 `.ppt`/`.pptx`；
- 输入服务器上的 PPT 目录；
- 选择默认或单页 Rubric；
- 配置模型、输出目录、topic 映射和并发数；
- 配置 API key、Base URL、DPI、网格数量和重试次数；
- 断点续跑、强制重新渲染、强制重新提取；
- 实时显示评估日志并停止任务；
- 展示汇总分、一级指标均分和各 PPT 结果；
- 下载完整的 `results.json`。

上传文件暂存在 `.web_runtime/uploads/<任务ID>/`。输出目录留空时，结果保存到
`output/web_<任务ID>/`。服务重启会清空内存任务列表，但不会删除 PPT 或结果文件。

## 运行（启用单页评分）

```bash
python -m pujiang_ppt_eval \
  --source /mnt/shared-storage-gpfs2/intern-pretrain-shared02/liuyanjiang/liushuainan/ppt_dataset/good \
  --output ./output/gemini_good_single_slide \
  --model gemini-2.5-flash-image \
  --rubric ./pujiang_ppt_eval/rubrics/with_single_slide.json \
  --workers 2 \
  --result-file results.json
```

示例新增一级指标 `Single_Slide_Quality`，包含 `Content_Clarity`、
`Visual_Effectiveness`、`Layout_Execution`。如果 PPT 有 26 页，会额外产生 26 次单页
VLM 请求。一级分数是 26 个逐页一级分数的算术平均。

该示例中新增权重为 `0.20`，全部一级权重总和为 `1.20`，所以归一化后的实际总分占比是
`0.20 / 1.20 = 16.67%`。

失败后断点续跑：

```bash
python -m pujiang_ppt_eval \
  --source /path/to/ppts \
  --output ./output/run1 \
  --model gemini-2.5-flash-image \
  --result-file results.json \
  --resume
```

编号文件建议提供真实主题：

```bash
python -m pujiang_ppt_eval ... --topic-map ./my_topics.json
```

`my_topics.json`：

```json
{"ultrapresent-valid-011": "真实主题", "ultrapresent-valid-024": "真实主题"}
```

## 新增或调整 Rubric

复制默认配置，不要直接修改默认基线：

```bash
cp pujiang_ppt_eval/rubrics/default.json my_rubric.json
```

每个一级指标结构如下：

```json
{
  "name": "Readability",
  "input_mode": "slide_images",
  "weight": 0.10,
  "description": "评价演示文稿的可读性",
  "subcriteria": [
    {"name": "Small_Text", "weight": 0.5, "description": "小字号文字是否仍清晰"},
    {"name": "Contrast", "weight": 0.5, "description": "前景与背景是否有足够对比"}
  ]
}
```

可用的 `input_mode`：

- `extracted_text`：使用整套 PPT 的逐页提取 Markdown；
- `slide_images`：使用幻灯片网格图片。
- `single_slide`：每张原始页面图独立调用 VLM，保留每页结果，再取平均得到整套分数。

然后运行：

```bash
python -m pujiang_ppt_eval ... --rubric ./my_rubric.json
```

提示词返回 Schema、字段完整性校验、逐项解释、一级指标分数和总分都会自动适配，无需修改 Python。
一级权重和子项权重不强制加和为 1，程序会分别归一化，因此扩展时不容易因漏改权重而破坏分数。

## 结果中的解释与单页字段

```json
{
  "scores": {"Content": 7.3},
  "sub_scores": {"Content": {"Logical_Flow": 8}},
  "score_explanations": {
    "Content": {"Logical_Flow": "为什么给8分的具体解释"}
  },
  "score_calculation": {
    "criteria": {"Content": {"formula": "Accuracy_and_Completeness×0.4 + ..."}},
    "weighted_total_formula": "Content×...，归一化为0-100"
  },
  "per_slide_scores": [
    {
      "slide_number": 1,
      "scores": {"Single_Slide_Quality": 7.65},
      "sub_scores": {"Single_Slide_Quality": {"Content_Clarity": 8}},
      "score_explanations": {
        "Single_Slide_Quality": {"Content_Clarity": "该页信息清晰……"}
      }
    }
  ]
}
```

模型缺少任何子分解释时，返回会被判定为不完整并自动重试。

## 维护边界

- 新 Rubric：只改 JSON。
- 新模型厂商：新增模型适配器，不动 evaluator。
- 新输入模态：新增处理组件，并在 evaluator 注册调用路径。
- 新报告格式：修改/扩展 reporting，不动评分代码。
- 新预处理方式：替换 SlidePreprocessor，不动 Rubric 和模型接口。

## 验证

```bash
python -m unittest discover -s tests -v
```

注意：未提供源文档，因此默认 Content 中的事实准确性仍是 VLM 根据幻灯片与自身知识作出的
主观判断，不等价于有参考答案的事实核验。
