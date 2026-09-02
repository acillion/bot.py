#!/usr/bin/env python3
"""
Test script for the bot using a mock RSS entry
"""
import json
import os

# Set up test environment
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("X_API_KEY", "test-key")
os.environ.setdefault("X_API_SECRET", "test-secret")
os.environ.setdefault("X_ACCESS_TOKEN", "test-token")
os.environ.setdefault("X_ACCESS_SECRET", "test-secret")

# Mock feedparser to return a test entry
import sys
from unittest.mock import MagicMock, patch

mock_entry = {
    'title': 'Real Madrid wins 3-0 against Barcelona! #HalaMadrid #RealMadrid 🔥',
    'summary': 'Brilliant performance by the team',
    'link': 'https://twitter.com/realmadriden/status/123456789',
    'id': 'tweet-123456789',
}

mock_feed = MagicMock()
mock_feed.entries = [mock_entry]
mock_feed.bozo = False

with patch('feedparser.parse', return_value=mock_feed):
    # Mock Gemini to return a translation
    with patch('google.generativeai.GenerativeModel') as mock_model_class:
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Real Madrid don hammer Barcelona 3-0! Dem boys play fine fine! #HalaMadrid 🔥"
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model_instance
        
        # Mock tweepy clients
        with patch('tweepy.Client') as mock_client:
            with patch('tweepy.OAuth1UserHandler'):
                with patch('tweepy.API') as mock_api:
                    with patch('google.generativeai.configure'):
                        # Import and run the bot
                        import bot
                        
                        print("=" * 60)
                        print("TEST RUN: Real Madrid Pidgin Bot")
                        print("=" * 60)
                        
                        # Run the pipeline
                        bot.run_pipeline()
                        
                        print("\n" + "=" * 60)
                        print("TEST COMPLETED")
                        print("=" * 60)
                        
                        # Check if processed_tweets.json was created
                        if os.path.exists("processed_tweets.json"):
                            with open("processed_tweets.json", "r") as f:
                                processed = json.load(f)
                            print(f"\n✓ processed_tweets.json created successfully")
                            print(f"  Processed entries: {processed}")
                        else:
                            print(f"\n✗ processed_tweets.json was NOT created")
