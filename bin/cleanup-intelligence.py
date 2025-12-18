#!/usr/bin/env python3
"""
Cleanup script for Jarvis Intelligence Database
Safely removes bad experiences, pending reflections, and low-quality insights
"""

import os
import sys
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import shutil

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

class IntelligenceCleanup:
    def __init__(self, mode='cloud', dry_run=True):
        self.mode = mode
        self.dry_run = dry_run
        self.project_root = Path(__file__).parent.parent
        
        # Determine database path
        if mode == 'local':
            self.db_path = self.project_root / 'data' / 'jarvis_intelligence_local.db'
        else:
            self.db_path = self.project_root / 'data' / 'jarvis_intelligence.db'
        
        if not self.db_path.exists():
            print(f"❌ Database not found: {self.db_path}")
            sys.exit(1)
        
        self.conn = None
        self.stats = {
            'pending_reflections_deleted': 0,
            'failed_experiences_deleted': 0,
            'low_confidence_insights_deleted': 0,
            'bad_feedback_archived': 0
        }
    
    def connect(self):
        """Connect to the database"""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def backup_database(self):
        """Create a backup before making changes"""
        if self.dry_run:
            print("🔍 [DRY RUN] Would create backup")
            return None
        
        backup_path = self.db_path.with_suffix(f'.db.backup-{datetime.now().strftime("%Y%m%d-%H%M%S")}')
        print(f"📦 Creating backup: {backup_path.name}")
        shutil.copy2(self.db_path, backup_path)
        return backup_path
    
    def show_current_stats(self):
        """Display current database statistics"""
        cursor = self.conn.cursor()
        
        print("\n📊 CURRENT DATABASE STATE")
        print("=" * 60)
        
        # Total counts
        cursor.execute("SELECT COUNT(*) as count FROM experiences")
        total_exp = cursor.fetchone()['count']
        print(f"Total Experiences: {total_exp}")
        
        cursor.execute("SELECT COUNT(*) as count FROM experiences WHERE outcome_success = 0")
        failed_exp = cursor.fetchone()['count']
        print(f"Failed Experiences: {failed_exp}")
        
        cursor.execute("SELECT COUNT(*) as count FROM reflection_queue WHERE processed = 0")
        pending = cursor.fetchone()['count']
        print(f"Pending Reflections: {pending}")
        
        cursor.execute("SELECT COUNT(*) as count FROM insights")
        total_insights = cursor.fetchone()['count']
        print(f"Total Insights: {total_insights}")
        
        cursor.execute("SELECT COUNT(*) as count FROM insights WHERE confidence < 0.3")
        low_conf = cursor.fetchone()['count']
        print(f"Low Confidence Insights (<0.3): {low_conf}")
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM insights 
            WHERE consecutive_failures >= 3
        """)
        bad_insights = cursor.fetchone()['count']
        print(f"Insights with 3+ Consecutive Failures: {bad_insights}")
        
        print("=" * 60)
    
    def clear_pending_reflections(self):
        """Clear all pending reflections from the queue"""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM reflection_queue WHERE processed = 0")
        count = cursor.fetchone()['count']
        
        if count == 0:
            print("\n✅ No pending reflections to clear")
            return
        
        print(f"\n🗑️  Clearing {count} pending reflections...")
        
        if not self.dry_run:
            # Delete pending reflections
            cursor.execute("DELETE FROM reflection_queue WHERE processed = 0")
            self.conn.commit()
            self.stats['pending_reflections_deleted'] = count
            print(f"✅ Deleted {count} pending reflections")
        else:
            print(f"🔍 [DRY RUN] Would delete {count} pending reflections")
            self.stats['pending_reflections_deleted'] = count
    
    def remove_failed_experiences(self, days_back=7):
        """Remove experiences marked as failures from recent testing"""
        cursor = self.conn.cursor()
        
        # Get cutoff date
        cutoff = datetime.now() - timedelta(days=days_back)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
        
        # Find failed experiences
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM experiences 
            WHERE outcome_success = 0 
            AND timestamp >= ?
        """, (cutoff_str,))
        count = cursor.fetchone()['count']
        
        if count == 0:
            print(f"\n✅ No failed experiences from last {days_back} days")
            return
        
        print(f"\n🗑️  Removing {count} failed experiences from last {days_back} days...")
        
        if not self.dry_run:
            # Get IDs first
            cursor.execute("""
                SELECT id FROM experiences 
                WHERE outcome_success = 0 
                AND timestamp >= ?
            """, (cutoff_str,))
            exp_ids = [row['id'] for row in cursor.fetchall()]
            
            # Delete related reflections first
            if exp_ids:
                placeholders = ','.join('?' * len(exp_ids))
                cursor.execute(f"""
                    DELETE FROM reflection_queue 
                    WHERE experience_id IN ({placeholders})
                """, exp_ids)
                
                # Delete experiences
                cursor.execute(f"""
                    DELETE FROM experiences 
                    WHERE id IN ({placeholders})
                """, exp_ids)
                
                self.conn.commit()
                self.stats['failed_experiences_deleted'] = count
                print(f"✅ Deleted {count} failed experiences and related reflections")
        else:
            print(f"🔍 [DRY RUN] Would delete {count} failed experiences")
            self.stats['failed_experiences_deleted'] = count
    
    def remove_low_quality_insights(self):
        """Remove insights with low confidence or repeated failures"""
        cursor = self.conn.cursor()
        
        # Find problematic insights
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM insights 
            WHERE confidence < 0.2 OR consecutive_failures >= 3
        """)
        count = cursor.fetchone()['count']
        
        if count == 0:
            print("\n✅ No low-quality insights to remove")
            return
        
        print(f"\n🗑️  Removing {count} low-quality insights...")
        print("    (confidence < 0.2 OR consecutive_failures >= 3)")
        
        if not self.dry_run:
            cursor.execute("""
                DELETE FROM insights 
                WHERE confidence < 0.2 OR consecutive_failures >= 3
            """)
            self.conn.commit()
            self.stats['low_confidence_insights_deleted'] = count
            print(f"✅ Deleted {count} low-quality insights")
        else:
            print(f"🔍 [DRY RUN] Would delete {count} low-quality insights")
            self.stats['low_confidence_insights_deleted'] = count
    
    def archive_bad_feedback(self, rating_threshold=2, days_back=7):
        """Archive feedback with low ratings"""
        feedback_dir = self.project_root / 'logs' / 'feedback'
        archive_dir = feedback_dir / 'archive'
        
        if not feedback_dir.exists():
            print("\n✅ No feedback directory found")
            return
        
        if not self.dry_run:
            archive_dir.mkdir(exist_ok=True)
        
        cutoff = datetime.now() - timedelta(days=days_back)
        bad_feedback_count = 0
        
        print(f"\n📦 Checking feedback files for bad ratings (≤{rating_threshold})...")
        
        # Process feedback files
        for feedback_file in sorted(feedback_dir.glob('feedback-*.jsonl')):
            # Parse date from filename
            try:
                date_str = feedback_file.stem.replace('feedback-', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                
                if file_date < cutoff:
                    continue
                
                # Count bad feedback
                with open(feedback_file, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            rating = entry.get('rating')
                            if rating is not None and rating <= rating_threshold:
                                bad_feedback_count += 1
                        except json.JSONDecodeError:
                            continue
                
            except (ValueError, IOError):
                continue
        
        if bad_feedback_count > 0:
            print(f"   Found {bad_feedback_count} feedback entries with rating ≤ {rating_threshold}")
            print(f"   (Feedback logs are kept for debugging - not deleted)")
        else:
            print(f"   ✅ No bad feedback found in last {days_back} days")
        
        self.stats['bad_feedback_archived'] = bad_feedback_count
    
    def optimize_database(self):
        """Vacuum and optimize the database"""
        if self.dry_run:
            print("\n🔍 [DRY RUN] Would optimize database (VACUUM)")
            return
        
        print("\n🔧 Optimizing database (VACUUM)...")
        cursor = self.conn.cursor()
        cursor.execute("VACUUM")
        self.conn.commit()
        print("✅ Database optimized")
    
    def show_summary(self):
        """Display cleanup summary"""
        print("\n" + "=" * 60)
        print("📊 CLEANUP SUMMARY")
        print("=" * 60)
        print(f"Pending Reflections Deleted: {self.stats['pending_reflections_deleted']}")
        print(f"Failed Experiences Deleted: {self.stats['failed_experiences_deleted']}")
        print(f"Low-Quality Insights Deleted: {self.stats['low_confidence_insights_deleted']}")
        print(f"Bad Feedback Entries Found: {self.stats['bad_feedback_archived']}")
        print("=" * 60)
        
        if self.dry_run:
            print("\n💡 This was a DRY RUN - no changes were made")
            print("   Run with --execute to actually perform the cleanup")
        else:
            print("\n✅ Cleanup completed successfully!")
    
    def run(self, clear_reflections=True, remove_failures=True, 
            remove_bad_insights=True, archive_feedback=True):
        """Run the complete cleanup process"""
        try:
            self.connect()
            
            print(f"\n{'🔍 DRY RUN MODE' if self.dry_run else '⚡ EXECUTE MODE'}")
            print(f"Database: {self.db_path.name}")
            
            self.show_current_stats()
            
            if not self.dry_run:
                backup_path = self.backup_database()
                if backup_path:
                    print(f"✅ Backup created: {backup_path.name}")
            
            if clear_reflections:
                self.clear_pending_reflections()
            
            if remove_failures:
                self.remove_failed_experiences(days_back=7)
            
            if remove_bad_insights:
                self.remove_low_quality_insights()
            
            if archive_feedback:
                self.archive_bad_feedback(rating_threshold=2, days_back=7)
            
            if not self.dry_run:
                self.optimize_database()
            
            self.show_summary()
            
            # Show new stats
            if not self.dry_run:
                print("\n")
                self.show_current_stats()
            
        finally:
            self.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Cleanup Jarvis Intelligence Database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview changes)
  %(prog)s --dry-run
  
  # Execute cleanup for cloud database
  %(prog)s --execute
  
  # Execute cleanup for local database
  %(prog)s --execute --mode local
  
  # Only clear pending reflections
  %(prog)s --execute --reflections-only
        """
    )
    
    parser.add_argument('--mode', choices=['cloud', 'local'], default='cloud',
                       help='Which database to clean (default: cloud)')
    parser.add_argument('--execute', action='store_true',
                       help='Actually perform the cleanup (default is dry-run)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Preview changes without executing (default)')
    parser.add_argument('--reflections-only', action='store_true',
                       help='Only clear pending reflections')
    
    args = parser.parse_args()
    
    # If --execute is passed, disable dry_run
    dry_run = not args.execute
    
    print("=" * 60)
    print("🧹 JARVIS INTELLIGENCE DATABASE CLEANUP")
    print("=" * 60)
    
    cleaner = IntelligenceCleanup(mode=args.mode, dry_run=dry_run)
    
    if args.reflections_only:
        cleaner.run(
            clear_reflections=True,
            remove_failures=False,
            remove_bad_insights=False,
            archive_feedback=False
        )
    else:
        cleaner.run()


if __name__ == '__main__':
    main()

