"""
Conversation Storage Service
Saves and loads chat conversations
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
import uuid

# Store conversations in data directory
CONVERSATIONS_DIR = Path(__file__).parent.parent.parent.parent / 'data' / 'web_conversations'


class ConversationStore:
    """Manages conversation persistence"""
    
    def __init__(self, conversations_dir: Path | None = None):
        self.conversations_dir = conversations_dir or CONVERSATIONS_DIR
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.conversations_dir / 'index.json'
        self._index = self._load_index()

    @staticmethod
    def _default_summary(
        conv_id: str,
        title: str,
        created_at: str,
        updated_at: str,
        message_count: int = 0,
    ) -> dict:
        return {
            'id': conv_id,
            'title': title,
            'created_at': created_at,
            'updated_at': updated_at,
            'message_count': message_count,
            'pinned': False,
            'archived': False,
            'pinned_at': None,
            'archived_at': None,
        }

    @staticmethod
    def _normalize_summary(summary: dict | None) -> dict:
        summary = dict(summary or {})
        summary.setdefault('message_count', 0)
        summary['pinned'] = bool(summary.get('pinned', False))
        summary['archived'] = bool(summary.get('archived', False))
        summary['pinned_at'] = summary.get('pinned_at')
        summary['archived_at'] = summary.get('archived_at')
        return summary

    @staticmethod
    def _normalize_conversation_metadata(conversation: dict | None) -> dict:
        conversation = dict(conversation or {})
        conversation['pinned'] = bool(conversation.get('pinned', False))
        conversation['archived'] = bool(conversation.get('archived', False))
        conversation['pinned_at'] = conversation.get('pinned_at')
        conversation['archived_at'] = conversation.get('archived_at')
        return conversation
    
    def _load_index(self) -> dict:
        """Load conversation index"""
        if self._index_file.exists():
            try:
                with open(self._index_file, 'r') as f:
                    loaded = json.load(f)
                    summaries = [
                        self._normalize_summary(item)
                        for item in loaded.get('conversations', [])
                    ]
                    return {'conversations': summaries}
            except Exception:
                pass
        return {'conversations': []}
    
    def _save_index(self):
        """Save conversation index"""
        with open(self._index_file, 'w') as f:
            json.dump(self._index, f, indent=2)
    
    def create_conversation(self, title: str = None) -> dict:
        """Create a new conversation"""
        conv_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        
        conversation = {
            'id': conv_id,
            'title': title or f'Chat {datetime.now().strftime("%m/%d %H:%M")}',
            'created_at': timestamp,
            'updated_at': timestamp,
            'messages': [],
            'pinned': False,
            'archived': False,
            'pinned_at': None,
            'archived_at': None,
        }
        
        # Save to file
        conv_file = self.conversations_dir / f'{conv_id}.json'
        with open(conv_file, 'w') as f:
            json.dump(conversation, f, indent=2)
        
        # Update index
        self._index['conversations'].insert(
            0,
            self._default_summary(
                conv_id,
                conversation['title'],
                timestamp,
                timestamp,
                message_count=0,
            ),
        )
        self._save_index()
        
        return conversation
    
    def get_conversation(self, conv_id: str) -> dict | None:
        """Get a conversation by ID"""
        conv_file = self.conversations_dir / f'{conv_id}.json'
        if conv_file.exists():
            with open(conv_file, 'r') as f:
                return self._normalize_conversation_metadata(json.load(f))
        return None
    
    def add_message(self, conv_id: str, role: str, content: str, 
                    data: dict = None, tools_used: list[str] = None) -> dict:
        """Add a message to a conversation"""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            conversation = self.create_conversation()
            conv_id = conversation['id']
        
        message = {
            'id': str(uuid.uuid4())[:8],
            'role': role,  # 'user' or 'assistant'
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'tools_used': tools_used or []
        }
        
        conversation['messages'].append(message)
        conversation['updated_at'] = message['timestamp']
        
        # Auto-generate title from first user message (full text; sidebar row ellipsizes in CSS)
        if len(conversation['messages']) == 1 and role == 'user':
            line = ' '.join(content.strip().split())
            if line:
                conversation['title'] = line[:4000]
        
        # Save conversation
        conv_file = self.conversations_dir / f'{conv_id}.json'
        with open(conv_file, 'w') as f:
            json.dump(conversation, f, indent=2)
        
        # Update index
        for idx_conv in self._index['conversations']:
            if idx_conv['id'] == conv_id:
                idx_conv['updated_at'] = message['timestamp']
                idx_conv['message_count'] = len(conversation['messages'])
                idx_conv['title'] = conversation['title']
                break
        self._save_index()
        
        return message
    
    def list_conversations(self, limit: int = 50, include_archived: bool = True) -> list[dict]:
        """List recent conversations, with pinned chats sorted first."""
        convs = [self._normalize_summary(item) for item in self._index['conversations']]
        if not include_archived:
            convs = [item for item in convs if not item.get('archived')]
        convs = sorted(
            convs,
            key=lambda item: (
                1 if item.get('pinned') and not item.get('archived') else 0,
                1 if not item.get('archived') else 0,
                item.get('pinned_at') or item.get('updated_at', ''),
                item.get('updated_at', ''),
            ),
            reverse=True,
        )
        return convs[:limit]
    
    def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation"""
        conv_file = self.conversations_dir / f'{conv_id}.json'
        if conv_file.exists():
            conv_file.unlink()
        
        self._index['conversations'] = [
            c for c in self._index['conversations'] if c['id'] != conv_id
        ]
        self._save_index()
        return True

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        """Parse saved conversation timestamps for retention cleanup."""
        if not value:
            return None
        try:
            timestamp = str(value)
            if timestamp.endswith('Z'):
                timestamp = f"{timestamp[:-1]}+00:00"
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    def cleanup_old_unpinned(
        self,
        *,
        retention_days: int = 90,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> dict:
        """Delete unpinned conversations older than the retention window."""
        now = now or datetime.now()
        cutoff = now - timedelta(days=retention_days)
        result = {
            'deleted_conversations': 0,
            'freed_bytes': 0,
            'preserved_pinned': 0,
            'preserved_recent': 0,
            'skipped_invalid_timestamp': 0,
            'missing_files': 0,
            'candidates': [],
            'warnings': [],
            'errors': [],
        }

        for summary in list(self._index.get('conversations', [])):
            summary = self._normalize_summary(summary)
            conv_id = summary.get('id')
            if not conv_id:
                continue

            conv_file = self.conversations_dir / f'{conv_id}.json'
            conversation = self.get_conversation(conv_id)
            if conversation is None:
                result['missing_files'] += 1
                conversation = {}

            if summary.get('pinned') or conversation.get('pinned'):
                result['preserved_pinned'] += 1
                continue

            timestamp = self._parse_timestamp(
                conversation.get('updated_at')
                or summary.get('updated_at')
                or conversation.get('created_at')
                or summary.get('created_at')
            )
            if timestamp is None:
                result['skipped_invalid_timestamp'] += 1
                result['warnings'].append({
                    'conversation_id': conv_id,
                    'warning': 'Missing or invalid updated_at timestamp',
                })
                continue
            if timestamp >= cutoff:
                result['preserved_recent'] += 1
                continue

            size = conv_file.stat().st_size if conv_file.exists() else 0
            result['candidates'].append({
                'id': conv_id,
                'title': conversation.get('title') or summary.get('title') or conv_id,
                'updated_at': timestamp.isoformat(),
                'size': size,
            })
            result['freed_bytes'] += size
            if dry_run:
                continue

            try:
                self.delete_conversation(conv_id)
                result['deleted_conversations'] += 1
            except Exception as exc:
                result['errors'].append({
                    'conversation_id': conv_id,
                    'error': str(exc),
                })
        return result
    
    def clear_conversation(self, conv_id: str) -> bool:
        """Clear all messages from a conversation (keeps the conversation, resets to empty)"""
        conversation = self.get_conversation(conv_id)
        if conversation:
            conversation['messages'] = []
            conversation['title'] = f'Chat {datetime.now().strftime("%m/%d %H:%M")}'
            conversation['updated_at'] = datetime.now().isoformat()
            conv_file = self.conversations_dir / f'{conv_id}.json'
            with open(conv_file, 'w') as f:
                json.dump(conversation, f, indent=2)
            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['updated_at'] = conversation['updated_at']
                    idx_conv['message_count'] = 0
                    idx_conv['title'] = conversation['title']
                    break
            self._save_index()
            return True
        return False

    def update_title(self, conv_id: str, title: str) -> bool:
        """Update conversation title"""
        conversation = self.get_conversation(conv_id)
        if conversation:
            conversation['title'] = title
            conv_file = self.conversations_dir / f'{conv_id}.json'
            with open(conv_file, 'w') as f:
                json.dump(conversation, f, indent=2)
            
            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['title'] = title
                    break
            self._save_index()
            return True
        return False

    def update_state(self, conv_id: str, *, pinned: bool | None = None, archived: bool | None = None) -> dict | None:
        """Update pinned/archive state for a conversation and return the updated summary."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return None

        timestamp = datetime.now().isoformat()
        if archived is not None:
            conversation['archived'] = bool(archived)
            conversation['archived_at'] = timestamp if conversation['archived'] else None
            if conversation['archived']:
                conversation['pinned'] = False
                conversation['pinned_at'] = None
        if pinned is not None and not conversation.get('archived'):
            conversation['pinned'] = bool(pinned)
            conversation['pinned_at'] = timestamp if conversation['pinned'] else None

        conv_file = self.conversations_dir / f'{conv_id}.json'
        with open(conv_file, 'w') as f:
            json.dump(conversation, f, indent=2)

        updated_summary = None
        for idx_conv in self._index['conversations']:
            if idx_conv['id'] != conv_id:
                continue
            idx_conv['pinned'] = conversation.get('pinned', False)
            idx_conv['archived'] = conversation.get('archived', False)
            idx_conv['pinned_at'] = conversation.get('pinned_at')
            idx_conv['archived_at'] = conversation.get('archived_at')
            updated_summary = dict(idx_conv)
            break
        self._save_index()
        return self._normalize_summary(updated_summary)

    def update_llm_metadata(
        self,
        conv_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> bool:
        """Persist the provider/model used for this conversation (for token UI restore)."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return False

        changed = False
        if provider and conversation.get('llm_provider') != provider:
            conversation['llm_provider'] = provider
            changed = True
        if model and conversation.get('llm_model') != model:
            conversation['llm_model'] = model
            changed = True
        if not changed:
            return True

        conversation['updated_at'] = datetime.now().isoformat()
        conv_file = self.conversations_dir / f'{conv_id}.json'
        with open(conv_file, 'w') as f:
            json.dump(conversation, f, indent=2)
        return True

    def update_message_data_by_web_message_id(self, conv_id: str, web_message_id: str, patch: dict) -> bool:
        """Merge message data into an assistant message identified by its live web message id."""
        conversation = self.get_conversation(conv_id)
        if not conversation:
            return False

        for message in conversation.get('messages', []):
            message_data = message.get('data') or {}
            if message_data.get('_web_message_id') != web_message_id:
                continue

            message_data.update(patch or {})
            message['data'] = message_data
            conversation['updated_at'] = datetime.now().isoformat()

            conv_file = self.conversations_dir / f'{conv_id}.json'
            with open(conv_file, 'w') as f:
                json.dump(conversation, f, indent=2)

            for idx_conv in self._index['conversations']:
                if idx_conv['id'] == conv_id:
                    idx_conv['updated_at'] = conversation['updated_at']
                    break
            self._save_index()
            return True

        return False


# Singleton instance
_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """Get or create the conversation store singleton"""
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store
