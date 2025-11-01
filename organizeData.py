import os
import re
import requests
from datetime import date, timedelta
from google.cloud import storage
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, jsonify

# ==============================
# CONFIG
# ==============================
API_KEY = "ADD YOUR API KEY - HIDDEN FOR GITHUB UPLOAD"
BUCKET_NAME = "informedbias-news-articles"
GOOGLE_SHEET_ID = "1qciUvjQdZxTuM-lB0i4EG8dCUEM2wkDGOpVTxqx2HF8"
ANALYZER_URL = "ADD YOUR CLOUD RUN URL - HIDDEN FOR GITHUB UPLOAD"


MIN_LENGTH = 1000
CATEGORIES = ["politics","business","science","environment","health","education"]


# Major providers list
MAJOR_PROVIDERS = [
    "https://www.bbc.co.uk",
    "https://www.cnn.com",
    "https://www.cbsnews.com",
    "https://www.foxnews.com",
    "https://www.apnews.com",
    "https://www.npr.org",
    "https://www.nbcnews.com",
    "https://www.washingtonpost.com",
    "https://abcnews.go.com",
    "https://www.nytimes.com",
    "https://www.wsj.com",
    "https://www.reuters.com",
    "https://www.usatoday.com",
    "https://www.bloomberg.com",
    "https://www.thehill.com"
]

# ==============================
# AUTH
# ==============================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
sheet = gspread.authorize(creds).open_by_key(GOOGLE_SHEET_ID).sheet1
storage_client = storage.Client.from_service_account_json("service_account.json")

# ==============================
# HELPERS
# ==============================
def sanitize_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "_", title)[:100]

def upload_to_gcs(category, title, text, url):
    fetch_date = date.today().isoformat()
    blob_path = f"{category}/{fetch_date}/{sanitize_filename(title)}.txt"
    bucket = storage_client.bucket(BUCKET_NAME)
    bucket.blob(blob_path).upload_from_string(
        f"{title}\nDate fetched: {fetch_date}\nURL: {url}\n\n{text}",
        content_type="text/plain"
    )
    return blob_path

def parse_article_content(content):
    lines = content.splitlines()
    if len(lines) < 4:
        return None
    return {
        "title": lines[0].strip(),
        "date": lines[1].replace("Date fetched:", "").strip(),
        "url": lines[2].replace("URL:", "").strip(),
        "text": "\n".join(lines[4:]).strip()
    }

def analyze_text(article_text):
    try:
        resp = requests.post(ANALYZER_URL, json={"text": article_text})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error analyzing text: {e}")
        return None

# ==============================
# FETCH + UPLOAD
# ==============================
def fetch_category_news(category, number=15, sort="publish-time"):
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    url = (
        f"https://api.worldnewsapi.com/search-news?"
        f"api-key={API_KEY}&categories={category}&source-countries=us&language=en"
        f"&number={number}&sort={sort}"
        f"&earliest-publish-date={yesterday_str}&latest-publish-date={today_str}"
    )
    resp = requests.get(url).json()
    articles = []
    for item in resp.get("news", []):
        text = item.get("text", "").strip()
        if len(text) < MIN_LENGTH:
            continue
        articles.append((category, item.get("title", "untitled"), text, item.get("url","")))
    return articles

def fetch_top_news():
    url = (
        f"https://api.worldnewsapi.com/top-news?"
        f"api-key={API_KEY}"
        f"&source-country=us"
        f"&language=en"
        f"&headlines-only=false"
        f"&max-news-per-cluster=1"
    )
    resp = requests.get(url).json()
    articles = []
    for cluster in resp.get("top_news", []):
        if cluster.get("news"):
            item = cluster["news"][0]
            text = item.get("text", "").strip()
            if len(text) < MIN_LENGTH:
                continue
            articles.append(("top_news", item.get("title", "untitled"), text, item.get("url", "")))
    return articles




def fetch_major_providers_news(source,number=15, sort="publish-time", earliest=None, latest=None):
    """Fetch news from major providers for all subjects."""
    if earliest is None:
        earliest = (date.today() - timedelta(days=2)).isoformat()
    if latest is None:
        latest = date.today().isoformat()
    url = (
        f"https://api.worldnewsapi.com/search-news?"
        f"api-key={API_KEY}"
        f"&news-sources={source}"
        f"&language=en"
        f"&number={number}"
        f"&sort={sort}"
        f"&earliest-publish-date={earliest}"
        f"&latest-publish-date={latest}"
        
    )
    print(f"Fetching major providers news from {earliest} to {latest} for sources: {MAJOR_PROVIDERS}")
    resp = requests.get(url).json()
    articles = []
    for item in resp.get("news", []):
        text = item.get("text","").strip()
        if len(text) < MIN_LENGTH:
            continue
        articles.append(("major_providers", item.get("title","untitled"), text, item.get("url","")))
    return articles

def fetch_and_upload_all():
    all_articles = []

    # Top news
    all_articles.extend(fetch_top_news())

    # Major providers (today)
    for source in MAJOR_PROVIDERS:
        all_articles.extend(fetch_major_providers_news(source,number=10))

    # Category news
    for cat in CATEGORIES:
        all_articles.extend(fetch_category_news(cat))

    # Upload all fetched articles to GCS
    for category, title, text, link in all_articles:
        upload_to_gcs(category, title, text, link)

    return len(all_articles)

# ==============================
# PROCESS ARTICLES
# ==============================
def process_articles():
    today_str = date.today().isoformat()
    existing_urls = set(sheet.col_values(2))
    for category in (CATEGORIES + ["major_providers", "top_news"]):
        prefix = f"{category}/{today_str}/"
        bucket = storage_client.bucket(BUCKET_NAME)
        for blob in bucket.list_blobs(prefix=prefix):
            article = parse_article_content(blob.download_as_text())
            if not article or article["url"] in existing_urls:
                continue
            result = analyze_text(article["text"])
            if not result:
                continue
            sheet.append_row([article["title"], article["url"], article["date"], category, str(result)])

# ==============================
# FLASK APP (for Cloud Run)
# ==============================
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status":"running"})

@app.route("/run-all", methods=["POST"])
def run_all():
    try:
        fetch_count = fetch_and_upload_all()
        process_articles()
        return jsonify({"status":"success","fetched": fetch_count}), 200
    except Exception as e:
        return jsonify({"status":"error","message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

