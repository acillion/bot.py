import os
import json
import requests
import feedparser
import tweepy
import google.generativeai as genai
from PIL import Image
import logging
import hashlib
import mimetypes

# ==============================================================================
# 1. CONFIGURATIONS & BRANDING (INSERT YOUR DETAILS HERE)
# ==============================================================================

# API Keys fetched from GitHub Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
X_API_KEY = os.environ.get("X_API_KEY")
X_API_SECRET = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

# Source feed & tracking log
RSS_FEED_URL = "https://xcancel.com/realmadriden"
PROCESSED_FILE = "processed_tweets.json"

# ---> INSERT YOUR BRAND SIGNATURE HERE <---
# This signature appends to the end of every translated tweet.
BRAND_SIGNATURE = " | @MadridInPidgin"

# ---> INSERT YOUR LOGO FILE NAME HERE <---
# Ensure this PNG file with a transparent background exists in your GitHub root folder.
LOGO_PATH = "logo.png"

# X/Twitter character limit used as a guard (conservative)
TWEET_CHAR_LIMIT = 280

# ==============================================================================
# 2. CLIENT & SYSTEM PROMPT SETUP
# ==============================================================================

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Validate important env vars early
missing_env = [name for name, val in (
    ("GEMINI_API_KEY", GEMINI_API_KEY),
    ("X_API_KEY", X_API_KEY),
    ("X_API_SECRET", X_API_SECRET),
    ("X_ACCESS_TOKEN", X_ACCESS_TOKEN),
    ("X_ACCESS_SECRET", X_ACCESS_SECRET),
) if not val]
if missing_env:
    logger.warning("Missing environment variables: %s", ", ".join(missing_env))

# Configure Gemini client (may raise if key is invalid)
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
except Exception as e:
    logger.warning("Could not configure Gemini model: %s", e)
    model = None

# X v2 Client for posting tweets
client = tweepy.Client(
    consumer_key=X_API_KEY,
    consumer_secret=X_API_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_SECRET,
)

# X v1.1 API specifically required for uploading media files
try:
    auth = tweepy.OAuth1UserHandler(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    api_v1 = tweepy.API(auth)
except Exception as e:
    logger.warning("Could not configure tweepy v1 client for media uploads: %s", e)
    api_v1 = None

SYSTEM_PROMPT = """
You are an expert sports translator specializing in authentic Nigerian Pidgin English.
Translate the following Real Madrid English tweet into high-energy, natural Nigerian Pidgin English.
Rules:
1. Keep the football banter alive using natural Nigerian football terms.
2. Retain all original player names, scores, match times, and hashtags (#RealMadrid, #HalaMadrid).
3. Preserve emojis.
4. Keep the output under 230 characters to leave room for the brand signature.
5. Return ONLY the translated text—no intro, no quotation marks, no extra commentary.
"""

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        try:
            with open(PROCESSED_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load processed file: %s", e)
            return []
    return []


def save_processed(data):
    try:
        with open(PROCESSED_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error("Failed to save processed file: %s", e)


def translate_to_pidgin(text):
    if not model:
        logger.error("Translation model not configured. Returning original text.")
        return text

    prompt = f"{SYSTEM_PROMPT}\n\nTweet to translate:\n{text}"
    try:
        response = model.generate_content(prompt)
        # Guard: response may not have .text consistently
        translated = getattr(response, "text", None) or getattr(response, "content", None) or str(response)
        return translated.strip()
    except Exception as e:
        logger.error("Translation failed: %s", e)
        return text


def _safe_request_get(url, stream=False, timeout=10):
    headers = {"User-Agent": "bot.py/1.0 (+https://github.com/acillion)"}
    try:
        return requests.get(url, stream=stream, timeout=timeout, headers=headers)
    except Exception as e:
        logger.error("Request to %s failed: %s", url, e)
        return None


def download_media(url):
    """
    Downloads media and returns a local filename or None.
    Detects file extension using content-type header if available.
    """
    res = _safe_request_get(url, stream=True)
    if not res or res.status_code != 200:
        logger.warning("Failed to download media %s (status=%s)", url, getattr(res, "status_code", None))
        return None

    content_type = res.headers.get("content-type", "")
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".jpg"
    local_filename = f"temp_media{ext}"

    try:
        with open(local_filename, 'wb') as f:
            for chunk in res.iter_content(1024):
                if chunk:
                    f.write(chunk)
        return local_filename
    except Exception as e:
        logger.error("Error saving media to %s: %s", local_filename, e)
        return None


def apply_watermark(image_path):
    """
    Overlays a transparent PNG logo onto the bottom-right corner of the image.
    Returns the path to the watermarked image (may be same as input).
    """
    if not os.path.exists(LOGO_PATH):
        logger.info("Logo file '%s' not found. Skipping watermark.", LOGO_PATH)
        return image_path

    try:
        base_image = Image.open(image_path).convert("RGBA")
        logo = Image.open(LOGO_PATH).convert("RGBA")

        # Resize logo to 15% of the base image's width (maintaining aspect ratio)
        base_width, base_height = base_image.size
        logo_aspect = logo.width / logo.height
        new_logo_width = int(base_width * 0.15)
        new_logo_height = int(new_logo_width / logo_aspect)
        logo = logo.resize((new_logo_width, new_logo_height), Image.Resampling.LANCZOS)

        # Position at bottom-right with 20px padding
        margin = 20
        x_pos = base_width - new_logo_width - margin
        y_pos = base_height - new_logo_height - margin

        # Composite logo onto base image
        watermarked = Image.new("RGBA", base_image.size)
        watermarked.paste(base_image, (0, 0))
        watermarked.paste(logo, (x_pos, y_pos), mask=logo)

        # Save as JPEG for upload
        output_path = "watermarked_temp.jpg"
        watermarked.convert("RGB").save(output_path, "JPEG", quality=95)
        return output_path
    except Exception as e:
        logger.error("Failed to apply watermark to %s: %s", image_path, e)
        return image_path


def _make_stable_id(entry):
    # Try several common fields, then fallback to a hash of link+title
    for key in ("id", "guid", "link"):
        val = entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if val:
            return str(val)

    # last resort: hash title+summary
    title = entry.get('title') or entry.get('summary') or ''
    link = entry.get('link') or ''
    s = (title + link).encode('utf-8')
    return hashlib.sha1(s).hexdigest()


# ==============================================================================
# 4. MAIN PIPELINE EXECUTION
# ==============================================================================

def run_pipeline():
    processed_ids = load_processed()
    logger.info("Parsing feed: %s", RSS_FEED_URL)
    feed = feedparser.parse(RSS_FEED_URL)

    if getattr(feed, 'bozo', False):
        logger.warning("Feed parser reported an error: %s", getattr(feed, 'bozo_exception', None))

    entries = getattr(feed, 'entries', []) or []
    if not entries:
        logger.info("No entries found in feed.")
        return

    # Check the 3 newest entries in feed (oldest-first iteration)
    for entry in reversed(entries[:3]):
        # Ensure entry is a dict-like for easier access
        if not isinstance(entry, dict):
            entry = dict(entry)

        tweet_id = _make_stable_id(entry)

        if tweet_id in processed_ids:
            logger.debug("Already processed %s, skipping.", tweet_id)
            continue

        tweet_text = entry.get('title') or entry.get('summary') or ''

        # Skip retweets commonly formatted as 'RT @user:'
        if tweet_text.startswith("RT @") or tweet_text.startswith("RT by"):
            logger.info("Skipping retweet-style entry: %s", tweet_text[:80])
            continue

        logger.info("Original Text: %s", tweet_text)

        # 1. Translate via Gemini
        pidgin_text = translate_to_pidgin(tweet_text)

        # 2. Append Signature and enforce character limit
        allowed = TWEET_CHAR_LIMIT - len(BRAND_SIGNATURE)
        if len(pidgin_text) > allowed:
            logger.info("Translated text too long (%d > %d). Truncating.", len(pidgin_text), allowed)
            pidgin_text = pidgin_text[:allowed - 1]
        final_tweet = f"{pidgin_text}{BRAND_SIGNATURE}"
        logger.info("Final Tweet: %s", final_tweet)

        # 3. Process Attached Image (if present)
        media_ids = []
        temp_files = []

        # Detect media via 'media_content', 'enclosures', or links marked as enclosure
        media_url = None
        if entry.get('media_content'):
            try:
                media_url = entry['media_content'][0].get('url')
            except Exception:
                media_url = None
        if not media_url and entry.get('enclosures'):
            try:
                media_url = entry['enclosures'][0].get('href') or entry['enclosures'][0].get('url')
            except Exception:
                media_url = None
        if not media_url and entry.get('links'):
            for l in entry['links']:
                if l.get('rel') == 'enclosure' and l.get('href'):
                    media_url = l.get('href')
                    break

        if media_url:
            saved_path = download_media(media_url)
            if saved_path:
                temp_files.append(saved_path)
                # Apply logo watermark
                final_image_path = apply_watermark(saved_path)
                if final_image_path and final_image_path not in temp_files:
                    temp_files.append(final_image_path)

                # Upload to X media endpoint if api_v1 is available
                if api_v1:
                    try:
                        uploaded_media = api_v1.media_upload(filename=final_image_path)
                        media_ids.append(uploaded_media.media_id_string)
                    except Exception as e:
                        logger.error("Failed to upload media to X: %s", e)
                else:
                    logger.warning("API v1 client not available; skipping media upload.")

        # 4. Publish to X
        try:
            if media_ids:
                client.create_tweet(text=final_tweet, media_ids=media_ids)
            else:
                client.create_tweet(text=final_tweet)
            logger.info("Successfully posted to X: %s", tweet_id)
            processed_ids.append(tweet_id)
        except Exception as e:
            logger.error("Error publishing tweet: %s", e)

        # Cleanup temp files for this entry
        for p in temp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                logger.debug("Failed to remove temp file %s: %s", p, e)

    # Keep the tracking log trimmed to the last 100 items
    save_processed(processed_ids[-100:])


if __name__ == "__main__":
    run_pipeline()
