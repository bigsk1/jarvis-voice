#!/usr/bin/env python3
"""
Text processing tool for summarization, keyword extraction, word/character counting, and sentiment analysis.
"""
import sys
import os
import json
import re
from collections import Counter
from typing import Dict, List, Any

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value

def count_stats(text: str) -> Dict[str, int]:
    """Count words, characters, sentences, and paragraphs."""
    # Remove extra whitespace
    text_clean = ' '.join(text.split())
    
    # Count characters (with and without spaces)
    chars_with_spaces = len(text)
    chars_without_spaces = len(text.replace(' ', '').replace('\n', '').replace('\t', ''))
    
    # Count words (split by whitespace)
    words = text.split()
    word_count = len(words)
    
    # Count sentences (basic: split by . ! ?)
    sentences = re.split(r'[.!?]+', text)
    sentence_count = len([s for s in sentences if s.strip()])
    
    # Count paragraphs (split by double newlines)
    paragraphs = re.split(r'\n\s*\n', text)
    paragraph_count = len([p for p in paragraphs if p.strip()])
    
    return {
        "words": word_count,
        "characters_with_spaces": chars_with_spaces,
        "characters_without_spaces": chars_without_spaces,
        "sentences": sentence_count,
        "paragraphs": paragraph_count
    }

def extract_keywords(text: str, top_n: int = 10) -> List[Dict[str, Any]]:
    """Extract keywords using frequency analysis with stopword filtering."""
    # Basic stopwords list
    stopwords = set([
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
        'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'will', 'with',
        'the', 'this', 'but', 'they', 'have', 'had', 'what', 'when', 'where', 'who',
        'which', 'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
        'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 'can', 'just', 'should', 'now', 'i', 'you', 'we', 'our'
    ])
    
    # Tokenize and clean
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    
    # Filter stopwords and count
    filtered_words = [w for w in words if w not in stopwords]
    word_freq = Counter(filtered_words)
    
    # Get top N keywords
    top_keywords = word_freq.most_common(top_n)
    
    return [{"keyword": word, "frequency": count} for word, count in top_keywords]

def basic_sentiment(text: str) -> Dict[str, Any]:
    """Basic sentiment analysis using keyword matching."""
    text_lower = text.lower()
    
    # Positive and negative word lists
    positive_words = set([
        'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'love',
        'happy', 'joy', 'beautiful', 'perfect', 'best', 'awesome', 'brilliant',
        'positive', 'success', 'successful', 'win', 'winner', 'pleased', 'delighted'
    ])
    
    negative_words = set([
        'bad', 'terrible', 'awful', 'horrible', 'hate', 'sad', 'angry', 'worst',
        'poor', 'negative', 'fail', 'failure', 'disappointed', 'disappointing',
        'unfortunate', 'problem', 'issue', 'wrong', 'error', 'difficult', 'hard'
    ])
    
    # Count positive and negative words
    words = re.findall(r'\b[a-z]+\b', text_lower)
    pos_count = sum(1 for w in words if w in positive_words)
    neg_count = sum(1 for w in words if w in negative_words)
    
    # Determine sentiment
    total_sentiment_words = pos_count + neg_count
    
    if total_sentiment_words == 0:
        sentiment = "neutral"
        confidence = 0.5
    elif pos_count > neg_count:
        sentiment = "positive"
        confidence = min(0.5 + (pos_count / (total_sentiment_words * 2)), 0.95)
    elif neg_count > pos_count:
        sentiment = "negative"
        confidence = min(0.5 + (neg_count / (total_sentiment_words * 2)), 0.95)
    else:
        sentiment = "neutral"
        confidence = 0.5
    
    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "positive_words": pos_count,
        "negative_words": neg_count
    }

def summarize_text(text: str, num_sentences: int = 3) -> str:
    """Extractive summarization: select most important sentences."""
    # Split into sentences
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 20]
    
    if len(sentences) <= num_sentences:
        return text.strip()
    
    # Score sentences by word frequency (simple extractive method)
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    word_freq = Counter(words)
    
    # Score each sentence
    sentence_scores = []
    for sentence in sentences:
        sentence_words = re.findall(r'\b[a-z]{3,}\b', sentence.lower())
        score = sum(word_freq.get(w, 0) for w in sentence_words)
        sentence_scores.append((score, sentence))
    
    # Sort by score and take top N
    sentence_scores.sort(reverse=True)
    top_sentences = [s for _, s in sentence_scores[:num_sentences]]
    
    # Return in original order
    summary_sentences = []
    for sentence in sentences:
        if sentence in top_sentences:
            summary_sentences.append(sentence)
    
    return '. '.join(summary_sentences) + '.'

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        text = args.get('text', '')
        operation = args.get('operation', 'summarize')  # summarize, keywords, count, sentiment
        
        if not text:
            raise ValueError("No text provided")
        
        result = {}
        speech = ""
        
        if operation == 'summarize':
            num_sentences = args.get('num_sentences', 3)
            summary = summarize_text(text, num_sentences)
            result['summary'] = summary
            speech = f"Summary: {summary}"
        
        elif operation == 'keywords':
            top_n = args.get('top_n', 10)
            keywords = extract_keywords(text, top_n)
            result['keywords'] = keywords
            top_words = [k['keyword'] for k in keywords[:5]]
            speech = f"Top keywords: {', '.join(top_words)}"
        
        elif operation == 'count':
            stats = count_stats(text)
            result['statistics'] = stats
            speech = f"Text contains {stats['words']} words, {stats['characters_with_spaces']} characters, {stats['sentences']} sentences, and {stats['paragraphs']} paragraphs"
        
        elif operation == 'sentiment':
            sentiment_result = basic_sentiment(text)
            result['sentiment'] = sentiment_result
            speech = f"Sentiment is {sentiment_result['sentiment']} with {int(sentiment_result['confidence']*100)}% confidence"
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": result
        }))
        
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "speech": f"Error: {e}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()