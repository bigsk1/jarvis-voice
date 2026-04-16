"""
Conversation Storage Service
Saves and loads chat conversations
"""
import json
from datetime import datetime
from pathlib import Path
import uuid

# Store conversations in data directory
CONVERSATIONS_DIR = Path(__file__).parent.parent.parent.parent / 'data' / 'web_conversations'


class ConversationStore:
    """Manages conversation persistence"""
    
    def __init__(self):
        self.conversations_dir = CONVERSATIONS_DIR
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.conversations_dir / 'index.json'
        self._index = self._load_index()
    
    def _load_index(self) -> dict:
        """Load conversation index"""
        if self._index_file.exists():
            try:
                with open(self._index_file, 'r') as f:
                    return json.load(f)
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
            'messages': []
        }
        
        # Save to file
        conv_file = self.conversations_dir / f'{conv_id}.json'
        with open(conv_file, 'w') as f:
            json.dump(conversation, f, indent=2)
        
        # Update index
        self._index['conversations'].insert(0, {
            'id': conv_id,
            'title': conversation['title'],
            'created_at': timestamp,
            'updated_at': timestamp,
            'message_count': 0
        })
        self._save_index()
        
        return conversation
    
    def get_conversation(self, conv_id: str) -> dict | None:
        """Get a conversation by ID"""
        conv_file = self.conversations_dir / f'{conv_id}.json'
        if conv_file.exists():
            with open(conv_file, 'r') as f:
                return json.load(f)
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
    
    def list_conversations(self, limit: int = 50) -> list[dict]:
        """List recent conversations"""
        # Sort by updated_at descending
        convs = sorted(
            self._index['conversations'],
            key=lambda x: x.get('updated_at', ''),
            reverse=True
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
