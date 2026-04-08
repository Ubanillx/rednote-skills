import argparse
from datetime import datetime
from action_delay import add_delay_argument, resolve_delay_seconds
from browser_profile import (
    close_profile_context,
    launch_profile_context,
    page_requires_login,
)
from note_content import extract_note_data, humanize_note_page_before_extract

def dump_note(note_url: str, delay_seconds: float = 0.0) -> str:
    """
    导出小红书笔记内容
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
                "python3 scripts/manual_login.py"
            )

        try:
            humanize_note_page_before_extract(page, "读取文章内容", delay_seconds)
            json_data = extract_note_data(page)
        except RuntimeError as exc:
            return f"❌ {exc}"
        markdown_content = generate_rednote_markdown(json_data)

        return markdown_content
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出小红书笔记内容")
    parser.add_argument("note_url", type=str, help="小红书笔记URL")
    add_delay_argument(parser)
    args = parser.parse_args()
    note_url = args.note_url
    delay_seconds = resolve_delay_seconds(args.delay_seconds)

    result = dump_note(note_url, delay_seconds)
    print(result)
