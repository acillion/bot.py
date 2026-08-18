import os
import json
import requests
import feedparser
import tweepy
import google.generativeai as genai
from PIL import Image

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
RSS_FEED_URL = "https://nitter.poast.org/realmadriden/rss"
PROCESSED_FILE = "processed_tweets.json"

# ---> INSERT YOUR BRAND SIGNATURE HERE <---
# This signature appends to the end of every translated tweet.
BRAND_SIGNATURE = " | @MadridInPidgin" 

# ---> INSERT YOUR LOGO FILE NAME HERE <---
# Ensure this PNG file with a transparent background exists in your GitHub root folder.
LOGO_PATH = "logo.png"

# ==============================================================================
# 2. CLIENT & SYSTEM PROMPT SETUP
# ==============================================================================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# X v2 Client for posting tweets
client = tweepy.Client(
    consumer_key=X_API_KEY, 
    consumer_secret=X_API_SECRET,
    access_token=X_ACCESS_TOKEN, 
    access_token_secret=X_ACCESS_SECRET
)

# X v1.1 API specifically required for uploading media files
auth = tweepy.OAuth1UserHandler(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
api_v1 = tweepy.API(auth)

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
        with open(PROCESSED_FILE, "r") as f:
            return json.load(f)
    return []

def save_processed(data):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(data, f)

def translate_to_pidgin(text):
    prompt = f"{SYSTEM_PROMPT}\n\nTweet to translate:\n{text}"
    response = model.generate_content(prompt)
    return response.text.strip()

def download_media(url):
    local_filename = "temp_media.jpg"
    res = requests.get(url, stream=True)
    if res.status_code == 200:
        with open(local_filename, 'wb') as f:
            for chunk in res.iter_content(1024):
                f.write(chunk)
        return local_filename
    return None

def apply_watermark(image_path):
    """
    Overlays a transparent PNG logo onto the bottom-right corner of the image.
    """
    if not os.path.exists(LOGO_PATH):
        print(f"Warning: Logo file '{LOGO_PATH}' not found. Skipping watermark.")
        return image_path
        
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

# ==============================================================================
# 4. MAIN PIPELINE EXECUTION
# ==============================================================================

def run_pipeline():
    processed_ids = load_processed()
    feed = feedparser.parse(RSS_FEED_URL)
    
    # Check the 3 newest entries in feed
    for entry in reversed(feed.entries[:3]):
        tweet_id = entry.id
        
        if tweet_id in processed_ids:
            continue
            
        tweet_text = entry.title
        
        # Skip retweets
        if tweet_text.startswith("RT by"):
            continue

        print(f"Original Text: {tweet_text}")
        
        # 1. Translate via Gemini
        pidgin_text = translate_to_pidgin(tweet_text)
        
        # 2. Append Signature
        final_tweet = f"{pidgin_text}{BRAND_SIGNATURE}"
        print(f"Final Tweet: {final_tweet}")
        
        # 3. Process Attached Image (if present)
        media_ids = []
        if 'media_content' in entry:
            media_url = entry.media_content[0]['url']
            saved_path = download_media(media_url)
            
            if saved_path:
                # Apply logo watermark
                final_image_path = apply_watermark(saved_path)
                
                # Upload to X media endpoint
                uploaded_media = api_v1.media_upload(filename=final_image_path)
                media_ids.append(uploaded_media.media_id_string)
                
                # Cleanup temporary image files from storage
                if os.path.exists(saved_path): 
                    os.remove(saved_path)
                if os.path.exists(final_image_path) and final_image_path != saved_path: 
                    os.remove(final_image_path)

        # 4. Publish to X
        try:
            if media_ids:
                client.create_tweet(text=final_tweet, media_ids=media_ids)
            else:
                client.create_tweet(text=final_tweet)
            print("Successfully posted to X!")
            processed_ids.append(tweet_id)
        except Exception as e:
            print(f"Error publishing tweet: {e}")
            
    # Keep the tracking log trimmed to the last 100 items
    save_processed(processed_ids[-100:])

if __name__ == "__main__":
    run_pipeline()
