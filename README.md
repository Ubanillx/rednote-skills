# rednote-skills

`rednote-skills` 是一个面向小红书工作流的 Skill 仓库。它通过共享的真实 Chrome 用户目录和 Patchright 驱动浏览器，复用同一份登录态完成一组常见操作：

- 保存笔记草稿
- 按关键词搜索并导出笔记链接
- 拉取指定主页下的笔记列表
- 导出笔记内容或评论上下文
- 执行点赞、收藏、关注、评论等互动动作

这个skill的核心目标不是“伪造一个临时浏览器”，而是围绕一份稳定、可复用的真实登录环境，串起小红书的检索、采集、互动和草稿处理

## Skill 定位

仓库中的 Skill 名称是 `rednote-skills`，定义见 [SKILL.md](/Users/zhiot/Codes/rednote-skills/SKILL.md)。

它适合这些场景：

- 已经有人类账号登录，想复用同一份浏览器状态做自动化
- 需要批量搜索小红书内容并导出可继续处理的链接
- 需要先读笔记，再基于真实内容生成更贴合上下文的评论
- 需要把“搜内容、整理素材、互动执行”做成一条稳定链路

它不适合这些场景：

- 需要无痕、一次性的临时浏览器会话
- 希望跳过真实登录或规避平台风控
- 希望让脚本自动生成空泛评论模板直接群发

## 核心原则

使用这个 skill 时，默认遵循以下规则：

1. 始终复用共享的真实 Chrome profile，不切换到临时 cookie 浏览器。
2. 从业务脚本开始，不要上来先强制跑 `validate_cookies.py`。
3. 如果脚本提示 `未登录小红书` 或要求运行 `python3 scripts/manual_login.py`，先手动登录，再重跑原命令。
4. 搜索、导出、发布草稿、点赞、收藏、关注、评论必须复用同一份登录态。
5. 评论或回复前，先读取目标笔记内容，再让 AI 基于真实内容生成最终文案，最后由脚本发送。
6. 不要让 Python 负责“代写评论并发送”；`comment_note.py` 只负责发送你明确传入的最终文本。

## 环境要求

- macOS
- 已安装 Google Chrome
- Python 3
- 一个可正常登录小红书的真实 Chrome 用户资料

Python 依赖见 [requirements.txt](/Users/zhiot/Codes/rednote-skills/requirements.txt)：

- `patchright==1.58.2`
- `openpyxl==3.1.5`

安装依赖：

```bash
pip3 install -r requirements.txt
```

## 浏览器配置

默认配置如下：

- Chrome 可执行文件：自动探测
- Chrome 源用户目录：`~/Library/Application Support/Google/Chrome`
- Chrome 运行时用户目录：`workspace tmp/rednote/chrome-user-data`
- Chrome profile：`Profile 2`   `自己新建一个google chrome个人资料`

可选环境变量：

- `REDNOTE_CHROME_PATH`
- `REDNOTE_CHROME_USER_DATA_DIR`
- `REDNOTE_CHROME_RUNTIME_USER_DATA_DIR`
- `REDNOTE_CHROME_PROFILE_DIRECTORY`

这些变量适合在以下情况中覆盖默认值：

- 你的 Chrome 安装路径不是默认位置
- 你要使用的登录账号不在 `Profile 2`
- 你想把运行期复制出的浏览器目录放到别的位置

## 快速开始

### 1. 首次准备

进入仓库并安装依赖：

```bash
cd /Users/zhiot/Codes/rednote-skills
pip3 install -r requirements.txt
```

### 2. 先跑业务脚本

这个 skill 的约定是“先跑业务命令，再按需登录”，而不是先做 cookie 探测。

例如，直接从搜索开始：

```bash
python3 scripts/search_note_by_key_word.py "关键词" --top_n 5 --delay-seconds 3
```

如果命令提示未登录，再执行手动登录：

```bash
python3 scripts/manual_login.py
```

登录完成后，重新运行刚才失败的业务命令。

可选的登录校验命令：

```bash
python3 scripts/validate_cookies.py
```

- 返回 `True` 表示当前已登录
- 返回 `False` 表示需要再次执行 `python3 scripts/manual_login.py`

## 常见工作流

### 保存草稿

`publish_note.py` 只保存到草稿箱，不会直接发布。

```bash
python3 scripts/publish_note.py
python3 scripts/publish_note.py "测试标题" "正文内容" --delay-seconds 5
python3 scripts/publish_note.py "测试｜图文混排" $'第一段\n\n[[image:/absolute/path/to/a.jpg]]\n\n第二段' --delay-seconds 5
```

说明：

- 正文支持内联图片占位符：`[[image:/absolute/path/to/file]]`
- 图片路径应使用绝对路径
- 保存草稿后浏览器会保持打开，方便人工复核

### 搜索与导出

按关键词搜索：

```bash
python3 scripts/search_note_by_key_word.py "关键词" --top_n 5 --delay-seconds 3
python3 scripts/search_note_by_key_word.py "关键词" --start-index 21 --end-index 40 --filter '{"sort_by":"最新","note_type":"图文"}' --delay-seconds 3
```

批量搜索：

```bash
python3 scripts/batch_search_keywords.py --input /absolute/path/to/keywords.json --top-n 5 --delay-seconds 3
```

生成评论素材：

```bash
python3 scripts/batch_generate_comment_materials.py --input /absolute/path/to/keywords.json --top-n 5 --delay-seconds 3
```

导出指定笔记内容：

```bash
python3 scripts/dump_note.py "<note_url>"
python3 scripts/dump_note.py "<note_url>" --format json --output /absolute/path/to/note.json
```

搜索说明：

- `search_note_by_key_word.py` 的返回结果是 Python `list` 形式的笔记 URL
- 首屏结果用 `--top_n`
- 瀑布流区间抓取用 `--start-index` 和 `--end-index`
- 更深范围可结合 `--max-scroll-rounds` 与 `--max-idle-scroll-rounds`
- `--filter` 支持排序、笔记类型、发布时间、搜索范围、位置距离等条件
- 保存笔记 URL 时要保留原始 `xsec_token` 和 `xsec_source`

### 拉取主页笔记

```bash
python3 scripts/list_profile_notes.py --profile-url "https://www.xiaohongshu.com/user/profile/<user_id>" --output /absolute/path/to/profile_notes.json
python3 scripts/list_profile_notes.py --user-id "<user_id>" --limit 0 --delay-seconds 3
```

说明：

- `--profile-url` 和 `--user-id` 二选一
- `--limit 0` 表示尽可能拉取页面可见的全部笔记
- 输出 JSON 中包含 `profile_url`、`count` 和 `notes`

### 批量收集→导出→转换

完整的工作流示例：从 URL 列表出发，经过去重、批量导出，最终生成 Excel 汇总表。

```bash
# Step 1: URL 去重（纯数据，不启动浏览器）
python3 scripts/dedup_urls.py \
  --input deliveries/bid_notes/bid_notes_raw.json \
  --output deliveries/bid_notes/unique_urls.json \
  --dedupe-path logs/rednote/note_dedupe_index_bid.json \
  --update-index

# Step 2: 批量导出笔记数据（启动浏览器）
python3 scripts/batch_dump_notes.py \
  --input deliveries/bid_notes/unique_urls.json \
  --output-dir deliveries/bid_notes \
  --dedupe-path logs/rednote/note_dedupe_index_bid.json \
  --limit 30 --delay-seconds 3

# Step 3: 转换为 Excel 汇总表（纯数据，不启动浏览器）
python3 scripts/convert_notes_to_xlsx.py \
  --input deliveries/bid_notes/<run_id>.json \
  --output deliveries/bid_notes/summary.xlsx \
  --columns "title,nickname,note_url,tags,desc,publish_time,liked_count"
```

说明：

- `dedup_urls.py` 只做 URL 级别的去重，不需要启动浏览器
- `batch_dump_notes.py` 会逐条打开笔记页面，自动去重（note_id + author），输出 JSON 和 XLSX
- `convert_notes_to_xlsx.py` 可以对任意步骤输出的 JSON 进行格式转换，支持自定义列
- 三个脚本可以独立使用，也可以串联成完整流水线

### 执行互动

```bash
python3 scripts/like_note.py "<note_url>" --delay-seconds 5
python3 scripts/collect_note.py "<note_url>" --delay-seconds 5
python3 scripts/follow_user.py "<note_url>" --delay-seconds 5
python3 scripts/comment_note.py "<note_url>" "<final_comment>" --delay-seconds 5 --like-probability 0.35
python3 scripts/batch_context_comments.py --input /absolute/path/to/comments.json --delay-seconds 5 --like-probability 0.35
```

评论流程必须遵守下面的顺序：

1. 先运行 `python3 scripts/dump_note.py "<note_url>"`
2. 基于真实笔记内容生成最终评论文本
3. 再运行 `python3 scripts/comment_note.py "<note_url>" "<final_comment>"`

评论硬规则：

- 不要发送空泛模板评论
- 评论必须基于当前笔记的标题、正文细节、标签、语气、情绪或观点
- `comment_note.py` 负责发送，不负责替你生成评论

## 批量输入格式

`batch_search_keywords.py` 支持这些输入结构：

```json
["关键词A", "关键词B"]
```

```json
[{"keyword": "关键词A", "top_n": 5}]
```

```json
{"items": [{"keyword": "关键词A", "top_n": 5}]}
```

```json
{"关键词A": 5, "关键词B": {"top_n": 8}}
```

每个 item 可包含：

- `keyword`
- `top_n`
- `start_index`
- `end_index`
- `max_scroll_rounds`
- `max_idle_scroll_rounds`
- `delay_seconds`
- `filter`
- `meta`

合并优先级：

- CLI `--filter` < 根级 `filter` < item 级 `filter`

如果只是想检查输入是否合法，可以先运行：

```bash
python3 scripts/batch_search_keywords.py --input /absolute/path/to/keywords.json --dry-run
```

## 文件与输出约定

目录约定：

- 最终交付物放到 `deliveries/`
- 运行日志放到 `logs/rednote/`
- 临时文件或调试文件放到 `tmp/rednote/`
- 不要把业务产物写进 `skills/` 或 `scripts/`

文件类型约定：

- `.json`：结构化输入输出
- `.jsonl`：追加式过程日志
- `.csv` / `.xlsx`：给人审阅和交付
- `.md`：总结、交接说明、运行说明

命名约定：

- 优先使用小写 snake_case
- 运行级时间戳优先使用 `YYYYMMDDTHHMMSS`
- 批处理结果可用 `batch_01_<keyword>.json`、`combined_50.json`、`summary.json`
- 能用 ASCII 就优先用 ASCII；只有业务关键字必须用中文时才保留中文

## 去重规则

这个 skill 内置了一套“笔记去重 + 作者去重”的操作规范，用来减少重复采集。

默认持久化文件：

- `logs/rednote/note_dedupe_index.json`

如果某个任务要单独维护去重范围，可以传：

- `--dedupe-path logs/rednote/note_dedupe_index_<topic>.json`

默认策略：

- 第一优先级：`note_id`
- 第二优先级：`author_key`
- 同一去重范围内，同一作者默认最多保留一条已采集笔记

重要规则：

- 不要把标题当作去重键
- 不要把关键词当作去重键
- 没有合法 `note_id` 的记录不要写进持久化去重索引
- 导出记录时保留原始笔记 URL，包括 `xsec_token` 和 `xsec_source`

## 仓库结构

当前仓库中比较关键的文件如下：

- [SKILL.md](/Users/zhiot/Codes/rednote-skills/SKILL.md)：Skill 定义、规则、命令和工作流说明
- [requirements.txt](/Users/zhiot/Codes/rednote-skills/requirements.txt)：Python 依赖
- [scripts/dedupe_utils.py](/Users/zhiot/Codes/rednote-skills/scripts/dedupe_utils.py)：共享去重工具模块
- [scripts/manual_login.py](/Users/zhiot/Codes/rednote-skills/scripts/manual_login.py)：手动登录
- [scripts/validate_cookies.py](/Users/zhiot/Codes/rednote-skills/scripts/validate_cookies.py)：登录态校验
- [scripts/publish_note.py](/Users/zhiot/Codes/rednote-skills/scripts/publish_note.py)：保存草稿
- [scripts/search_note_by_key_word.py](/Users/zhiot/Codes/rednote-skills/scripts/search_note_by_key_word.py)：关键词搜索
- [scripts/batch_search_keywords.py](/Users/zhiot/Codes/rednote-skills/scripts/batch_search_keywords.py)：批量搜索
- [scripts/batch_generate_comment_materials.py](/Users/zhiot/Codes/rednote-skills/scripts/batch_generate_comment_materials.py)：批量生成评论素材数据
- [scripts/batch_dump_notes.py](/Users/zhiot/Codes/rednote-skills/scripts/batch_dump_notes.py)：批量导出笔记数据（JSON + XLSX）
- [scripts/dedup_urls.py](/Users/zhiot/Codes/rednote-skills/scripts/dedup_urls.py)：URL 去重（纯数据，不启动浏览器）
- [scripts/convert_notes_to_xlsx.py](/Users/zhiot/Codes/rednote-skills/scripts/convert_notes_to_xlsx.py)：JSON 笔记转 Excel（纯数据）
- [scripts/list_profile_notes.py](/Users/zhiot/Codes/rednote-skills/scripts/list_profile_notes.py)：主页笔记列表
- [scripts/dump_note.py](/Users/zhiot/Codes/rednote-skills/scripts/dump_note.py)：导出单条笔记详情（支持 markdown/json）
- [scripts/export_profile_note_comments.py](/Users/zhiot/Codes/rednote-skills/scripts/export_profile_note_comments.py)：导出主页笔记短评 Excel/JSON
- [scripts/comment_note.py](/Users/zhiot/Codes/rednote-skills/scripts/comment_note.py)：发送评论
- [scripts/like_note.py](/Users/zhiot/Codes/rednote-skills/scripts/like_note.py)：点赞
- [scripts/collect_note.py](/Users/zhiot/Codes/rednote-skills/scripts/collect_note.py)：收藏
- [scripts/follow_user.py](/Users/zhiot/Codes/rednote-skills/scripts/follow_user.py)：关注
- [scripts/batch_context_comments.py](/Users/zhiot/Codes/rednote-skills/scripts/batch_context_comments.py)：批量发送上下文评论

## 风险与注意事项

- 该仓库依赖真实浏览器 profile，执行前请确认账号、资料目录和权限配置正确。
- 自动化动作可能受到平台页面结构变化、登录态过期或风控机制影响。
- 评论和互动行为应始终基于真实内容与明确意图，不建议做无差别批量模板化操作。
