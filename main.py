import feedparser
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
import json
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
import difflib
import re

# Настройки
SOURCES = [
    {"name": "TMZ", "url": "https://tmz.com/rss.xml"},
    {"name": "Page Six", "url": "https://pagesix.com/feed/"},
    {"name": "Us Weekly", "url": "https://www.usmagazine.com/category/celebrity-news/feed/"},
    {"name": "Deadline", "url": "https://deadline.com/feed/"},
    {"name": "Variety", "url": "https://variety.com/feed/"},
]

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASS = os.getenv("SMTP_PASS")
TO_EMAIL = os.getenv("TO_EMAIL")

SEEN_FILE = "seen_articles.json"

# Загрузка истории
seen = []
if os.path.exists(SEEN_FILE):
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen = json.load(f)
    except:
        seen = []

def is_recent(entry):
    """Проверяем, что статья за последние 24 часа"""
    for date_field in ["published", "updated", "pubDate"]:
        if date_field in entry:
            try:
                pub_date = feedparser.parse(entry[date_field]).feed.get("published_parsed") or entry.get("published_parsed")
                if pub_date:
                    pub_dt = datetime(*pub_date[:6])
                    return pub_dt > datetime.now() - timedelta(days=1)
            except:
                continue
    # Если дату не удалось распарсить — берём статью (на всякий случай)
    return True

def get_full_text(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return "\n".join(text.splitlines())[:4000]  # ограничиваем
    except Exception as e:
        print(f"Не удалось получить текст {url}: {e}")
        return ""

def translate_text(text):
    if not text or len(text.strip()) < 10:
        return text
    try:
        translator = GoogleTranslator(source='auto', target='ru')
        return translator.translate(text)
    except Exception as e:
        print(f"Ошибка перевода: {e}")
        return text

def normalize_text(text):
    return re.sub(r'\s+', ' ', text.lower().strip())

def articles_similar(a, b, threshold=0.70):
    text_a = normalize_text(a.get("title", "") + " " + a.get("summary", "")[:300])
    text_b = normalize_text(b.get("title", "") + " " + b.get("summary", "")[:300])
    return difflib.SequenceMatcher(None, text_a, text_b).ratio() > threshold

print("=== Запуск шоу-биз дайджеста ===")

new_articles = []
for source in SOURCES:
    print(f"→ Собираем {source['name']}...")
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries:
            if not is_recent(entry):
                continue
            url = entry.link
            if url in seen:
                continue

            full_text = get_full_text(url)
            article = {
                "url": url,
                "title": entry.title,
                "summary": entry.get("summary", ""),
                "full_text": full_text or entry.get("summary", ""),
                "source": source["name"]
            }
            new_articles.append(article)
            time.sleep(1.5)
    except Exception as e:
        print(f"Ошибка при обработке {source['name']}: {e}")

print(f"Найдено новых статей: {len(new_articles)}")

# Объединение похожих
unique_articles = []
for article in new_articles:
    merged = False
    for u in unique_articles:
        if articles_similar(article, u):
            u["full_text"] += "\n\n[Из " + article["source"] + "]\n" + article["full_text"][:1000]
            u["sources"] = u.get("sources", [u["source"]]) + [article["source"]]
            merged = True
            break
    if not merged:
        article["sources"] = [article["source"]]
        unique_articles.append(article)

# Формирование письма
if not unique_articles:
    print("Нет новых статей за последние 24 часа.")
else:
    digest_html = f"<h1>🎭 Шоу-бизнес дайджест — {datetime.now().strftime('%d %B %Y')}</h1><p>Найдено уникальных новостей: {len(unique_articles)}</p><hr>"

    for i, art in enumerate(unique_articles[:12], 1):
        ru_title = translate_text(art["title"])
        ru_text = translate_text(art["full_text"])
        sources_str = ", ".join(set(art["sources"]))
        
        digest_html += f"""
        <h2>{i}. {ru_title}</h2>
        <p><strong>Источники:</strong> {sources_str}</p>
        <p><a href="{art['url']}">Оригинал →</a></p>
        <div style="line-height: 1.7; margin: 15px 0;">
            {ru_text.replace('\n', '<br>')}
        </div>
        <hr>
        """

    # Отправка
    if SMTP_EMAIL and SMTP_PASS and TO_EMAIL:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎭 Шоу-биз дайджест — {datetime.now().strftime('%d.%m.%Y')}"
        msg["From"] = SMTP_EMAIL
        msg["To"] = TO_EMAIL
        msg.attach(MIMEText(digest_html, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SMTP_EMAIL, SMTP_PASS)
                server.send_message(msg)
            print("✅ Дайджест успешно отправлен на почту!")
        except Exception as e:
            print(f"❌ Ошибка отправки письма: {e}")
    else:
        print("❌ Не настроены SMTP секреты")

# Обновление seen
for art in unique_articles:
    if art["url"] not in seen:
        seen.append(art["url"])

with open(SEEN_FILE, "w", encoding="utf-8") as f:
    json.dump(seen[-800:], f, ensure_ascii=False, indent=2)

print(f"Готово. Всего в истории: {len(seen)} URL")
