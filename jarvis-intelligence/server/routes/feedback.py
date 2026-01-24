"""
Feedback routes for Jarvis Intelligence Dashboard
Serves feedback logs from logs/feedback/
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Blueprint, jsonify, request

# Paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
FEEDBACK_DIR = JARVIS_ROOT / 'logs' / 'feedback'

feedback_bp = Blueprint('feedback', __name__, url_prefix='/api/feedback')


def parse_feedback_file(filepath: Path) -> list:
    """Parse a JSONL feedback file."""
    entries = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        # Add date from filename for easier filtering
                        entry['_date'] = filepath.stem.replace('feedback-', '')
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return entries


@feedback_bp.route('/', methods=['GET'])
def list_feedback():
    """
    List feedback entries with optional filtering.
    
    Query params:
        - days: Number of days to look back (default: 30)
        - rating_max: Maximum rating to include (e.g., 3 for issues only)
        - rating_min: Minimum rating to include
        - mode: cloud or local
        - limit: Max entries to return (default: 100)
    """
    days = request.args.get('days', 30, type=int)
    rating_max = request.args.get('rating_max', 5, type=int)
    rating_min = request.args.get('rating_min', 1, type=int)
    mode_filter = request.args.get('mode', '')
    limit = request.args.get('limit', 100, type=int)
    
    if not FEEDBACK_DIR.exists():
        return jsonify({'ok': True, 'feedback': [], 'total': 0})
    
    # Get files from last N days
    cutoff = datetime.now() - timedelta(days=days)
    all_entries = []
    
    for filepath in sorted(FEEDBACK_DIR.glob('feedback-*.jsonl'), reverse=True):
        # Parse date from filename
        try:
            file_date = datetime.strptime(filepath.stem.replace('feedback-', ''), '%Y-%m-%d')
            if file_date < cutoff:
                continue
        except ValueError:
            continue
        
        entries = parse_feedback_file(filepath)
        all_entries.extend(entries)
    
    # Apply filters
    filtered = []
    for entry in all_entries:
        rating = entry.get('rating', 0)
        if rating < rating_min or rating > rating_max:
            continue
        if mode_filter and entry.get('mode') != mode_filter:
            continue
        filtered.append(entry)
    
    # Sort by timestamp descending
    filtered.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Apply limit
    total = len(filtered)
    filtered = filtered[:limit]
    
    return jsonify({
        'ok': True,
        'feedback': filtered,
        'total': total,
        'showing': len(filtered)
    })


@feedback_bp.route('/stats', methods=['GET'])
def feedback_stats():
    """
    Get feedback statistics.
    
    Query params:
        - days: Number of days to analyze (default: 30)
        - mode: cloud or local (optional)
    """
    days = request.args.get('days', 30, type=int)
    mode_filter = request.args.get('mode', '')
    
    if not FEEDBACK_DIR.exists():
        return jsonify({
            'ok': True,
            'stats': {
                'total': 0,
                'by_rating': {},
                'avg_rating': 0,
                'issues_by_category': {},
                'tool_ratings': {}
            }
        })
    
    cutoff = datetime.now() - timedelta(days=days)
    all_entries = []
    
    for filepath in sorted(FEEDBACK_DIR.glob('feedback-*.jsonl'), reverse=True):
        try:
            file_date = datetime.strptime(filepath.stem.replace('feedback-', ''), '%Y-%m-%d')
            if file_date < cutoff:
                continue
        except ValueError:
            continue
        
        entries = parse_feedback_file(filepath)
        if mode_filter:
            entries = [e for e in entries if e.get('mode') == mode_filter]
        all_entries.extend(entries)
    
    # Calculate stats
    by_rating = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    issues_by_category = {}
    tool_ratings = {}
    total_rating = 0
    
    for entry in all_entries:
        rating = entry.get('rating', 0)
        if 1 <= rating <= 5:
            by_rating[rating] += 1
            total_rating += rating
        
        # Count issues by category
        for issue in entry.get('issues', []):
            cat = issue.get('category', 'other')
            issues_by_category[cat] = issues_by_category.get(cat, 0) + 1
        
        # Aggregate tool ratings
        for tool_name, tool_data in entry.get('tool_ratings', {}).items():
            if tool_name not in tool_ratings:
                tool_ratings[tool_name] = {'total': 0, 'count': 0}
            tool_ratings[tool_name]['total'] += tool_data.get('rating', 0)
            tool_ratings[tool_name]['count'] += 1
    
    # Calculate averages
    total = len(all_entries)
    avg_rating = round(total_rating / total, 2) if total > 0 else 0
    
    for tool_name in tool_ratings:
        count = tool_ratings[tool_name]['count']
        if count > 0:
            tool_ratings[tool_name]['avg'] = round(tool_ratings[tool_name]['total'] / count, 2)
    
    return jsonify({
        'ok': True,
        'stats': {
            'total': total,
            'by_rating': by_rating,
            'avg_rating': avg_rating,
            'issues_by_category': issues_by_category,
            'tool_ratings': tool_ratings,
            'days_analyzed': days
        }
    })


@feedback_bp.route('/files', methods=['GET'])
def list_files():
    """List available feedback files."""
    if not FEEDBACK_DIR.exists():
        return jsonify({'ok': True, 'files': []})
    
    files = []
    for filepath in sorted(FEEDBACK_DIR.glob('feedback-*.jsonl'), reverse=True):
        try:
            entries = parse_feedback_file(filepath)
            files.append({
                'filename': filepath.name,
                'date': filepath.stem.replace('feedback-', ''),
                'count': len(entries),
                'size_kb': round(filepath.stat().st_size / 1024, 1)
            })
        except Exception:
            continue
    
    return jsonify({'ok': True, 'files': files})
