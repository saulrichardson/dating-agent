"""
Minimal context storage service for tracking conversation context per user per match.
"""

import json
import os
from pathlib import Path
from typing import Optional


class ContextStorage:
    """Simple file-based storage for conversation context."""
    
    def __init__(self, storage_file: str = "context_storage.json"):
        self.storage_file = Path(storage_file)
        self._data = self._load()
    
    def _load(self) -> dict:
        """Load context data from file."""
        if self.storage_file.exists():
            if self.storage_file.is_dir():
                return {}
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save(self):
        """Save context data to file."""
        if self.storage_file.exists() and self.storage_file.is_dir():
            raise ValueError(f"Storage path {self.storage_file} is a directory, not a file")
        with open(self.storage_file, 'w') as f:
            json.dump(self._data, f, indent=2)
    
    def get_key(self, user_id: str, match_id: str) -> str:
        """Generate storage key from user_id and match_id."""
        return f"{user_id}:{match_id}"
    
    def get_context(self, user_id: str, match_id: str) -> Optional[str]:
        """Get context for a user-match pair."""
        key = self.get_key(user_id, match_id)
        return self._data.get(key)
    
    def set_context(self, user_id: str, match_id: str, context: str):
        """Set context for a user-match pair."""
        key = self.get_key(user_id, match_id)
        self._data[key] = context
        self._save()
    
    def delete_context(self, user_id: str, match_id: str):
        """Delete context for a user-match pair."""
        key = self.get_key(user_id, match_id)
        if key in self._data:
            del self._data[key]
            self._save()
    
    def get_all_contexts(self, user_id: Optional[str] = None) -> dict:
        """Get all contexts, optionally filtered by user_id."""
        if user_id:
            return {
                k: v for k, v in self._data.items()
                if k.startswith(f"{user_id}:")
            }
        return self._data.copy()

