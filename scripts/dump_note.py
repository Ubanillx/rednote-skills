import argparse
import json
from datetime import datetime
from pathlib import Path
from action_delay import add_delay_argument, resolve_delay_seconds
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from note_content import extract_note_data, humanize_note_page_before_extract

def dump_note(note_url: str, delay_seconds: float = 0.0) -> tuple:
    """
    导出小红书笔记内容

    Returns:
        tuple: (markdown_content, json_data) where json_data is the raw API
        response dict on success, or None on error. markdown_content is the
        formatted markdown string (or an error message string).
    """
    driver, browser, context, page, settings, chrome_process = launch_profile_context(
        headless=False,
        startup_url=note_url,
    )
    try:
        print("🌐 导航到小红书笔记页面...")
        page.wait_for_timeout(1000)
        if page_requires_login(page):
            return (
                f'❌ 当前 Chrome {settings["profile_directory"]} 未登录小红书，请先运行 '
                "python3 scripts/manual_login.py",
                None,
            )

        try:
            humanize_note_page_before_extract(page, "读取文章内容", delay_seconds)
            json_data = extract_note_data(page)
        except RuntimeError as exc:
            return f"❌ {exc}", None
        markdown_content = generate_rednote_markdown(json_data)

        return markdown_content, json_data
    finally:
        close_profile_context(
            driver,
            browser,
            page=page,
            settings=settings,
            chrome_process=chrome_process,
        )
    
def generate_rednote_markdown(json_data):
    # 提取数据
    note_type = json_data['type']
    title = json_data['title']
    desc = json_data['desc']
    nickname = json_data['user']['nickname']
    avatar = json_data['user']['avatar']
    tags = [tag['name'] for tag in json_data['tagList']]
    liked_count = json_data['interactInfo']['likedCount']
    collected_count = json_data['interactInfo']['collectedCount']
    comment_count = json_data['interactInfo']['commentCount']
    share_count = json_data['interactInfo']['shareCount']
    create_time = datetime.fromtimestamp(json_data['time']/1000)
    update_time = datetime.fromtimestamp(json_data['lastUpdateTime']/1000)
    images = [image['urlDefault'] for image in json_data['imageList']] if 'imageList' in json_data else []
    video_url = json_data['video']['media']['stream']['h264'][0]['masterUrl'] if 'video' in json_data else None
    ip_location = json_data.get('ipLocation', '')
    
    # 生成 Markdown
    markdown = f"""# {title}

<div align="center">
<img src="{avatar}" width="50" style="border-radius: 50%;" />

**{nickname}**
</div>

"""
    
    # 添加媒体内容
    if note_type == "video" and video_url:
        markdown += f"""## 🎬 视频

<div style="position: relative; width: 100%; padding-top: 56.25%;">
    <iframe 
        src="{video_url}" 
        style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"
        scrolling="no" 
        border="0" 
        frameborder="no" 
        allowfullscreen="true">
    </iframe>
</div>

""" 
    if note_type == "normal" and images:
        markdown += """## 🖼️ 图片

"""
        for idx, img_url in enumerate(images, 1):
            markdown += f"![图片{idx}]({img_url})\n\n"
    
    # 添加互动数据
    markdown += f"""

## 📝 正文

{desc}

## 🏷️ 标签

{' '.join([f'`#{tag}`' for tag in tags])}

## 📊 互动数据

| 👍 点赞 | ⭐ 收藏 | 💬 评论 | 🔗 分享 |
|:---:|:---:|:---:|:---:|
| {liked_count} | {collected_count} | {comment_count} | {share_count} |

## ℹ️ 其他信息

- **发布时间**：{create_time.strftime('%Y-%m-%d %H:%M:%S')}
- **更新时间**：{update_time.strftime('%Y-%m-%d %H:%M:%S')}
- **IP 属地**：{ip_location}
- **内容类型**：{'📹 视频' if note_type == 'video' else '📷 图文'}
"""
    
    return markdown


def generate_note_json(json_data: dict, note_url: str) -> dict:
    """
    从原始笔记数据生成结构化字典，适合 JSON 序列化。

    Args:
        json_data: extract_note_data() 返回的原始 API 数据字典。
        note_url: 笔记的原始 URL。

    Returns:
        dict: 包含 note_id, note_url, title, desc, tags, nickname, avatar,
        note_type, publish_time, update_time, ip_location, liked_count,
        collected_count, comment_count, share_count, image_urls, video_url。
    """
    note_type = json_data.get("type", "")
    create_time = datetime.fromtimestamp(json_data["time"] / 1000)
    update_time = datetime.fromtimestamp(json_data["lastUpdateTime"] / 1000)
    images = (
        [image["urlDefault"] for image in json_data["imageList"]]
        if "imageList" in json_data
        else []
    )
    video_url = (
        json_data["video"]["media"]["stream"]["h264"][0]["masterUrl"]
        if "video" in json_data
        else None
    )

    return {
        "note_id": json_data.get("noteId", ""),
        "note_url": note_url,
        "title": json_data.get("title", ""),
        "desc": json_data.get("desc", ""),
        "tags": [tag["name"] for tag in json_data.get("tagList", [])],
        "nickname": json_data["user"].get("nickname", ""),
        "avatar": json_data["user"].get("avatar", ""),
        "note_type": note_type,
        "publish_time": create_time.isoformat(),
        "update_time": update_time.isoformat(),
        "ip_location": json_data.get("ipLocation", ""),
        "liked_count": json_data["interactInfo"].get("likedCount", ""),
        "collected_count": json_data["interactInfo"].get("collectedCount", ""),
        "comment_count": json_data["interactInfo"].get("commentCount", ""),
        "share_count": json_data["interactInfo"].get("shareCount", ""),
        "image_urls": images,
        "video_url": video_url,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出小红书笔记内容")
    parser.add_argument("note_url", type=str, help="小红书笔记URL")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式 (默认: markdown)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径 (默认: 输出到 stdout)",
    )
    add_delay_argument(parser)
    args = parser.parse_args()
    note_url = args.note_url
    delay_seconds = resolve_delay_seconds(args.delay_seconds)

    markdown_content, json_data = dump_note(note_url, delay_seconds)

    if args.format == "json" and json_data is not None:
        output_text = json.dumps(
            generate_note_json(json_data, note_url),
            ensure_ascii=False,
            indent=2,
        )
    else:
        output_text = markdown_content

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
        print(f"✅ 已保存到 {output_path}")
    else:
        print(output_text)
