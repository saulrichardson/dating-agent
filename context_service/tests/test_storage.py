"""Tests for storage module."""
import json
import tempfile
from pathlib import Path
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from storage import ContextStorage


def test_storage_init_empty():
    """Test storage initialization with empty file."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage = ContextStorage(temp_file)
        assert storage._data == {}
    finally:
        Path(temp_file).unlink()


def test_set_and_get_context():
    """Test setting and getting context."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage = ContextStorage(temp_file)
        storage.set_context("user1", "match1", "test context")
        assert storage.get_context("user1", "match1") == "test context"
    finally:
        Path(temp_file).unlink()


def test_get_nonexistent_context():
    """Test getting context that doesn't exist."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage = ContextStorage(temp_file)
        assert storage.get_context("user1", "match1") is None
    finally:
        Path(temp_file).unlink()


def test_delete_context():
    """Test deleting context."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage = ContextStorage(temp_file)
        storage.set_context("user1", "match1", "test context")
        storage.delete_context("user1", "match1")
        assert storage.get_context("user1", "match1") is None
    finally:
        Path(temp_file).unlink()


def test_get_all_contexts_for_user():
    """Test getting all contexts for a user."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage = ContextStorage(temp_file)
        storage.set_context("user1", "match1", "context1")
        storage.set_context("user1", "match2", "context2")
        storage.set_context("user2", "match1", "context3")
        
        user1_contexts = storage.get_all_contexts("user1")
        assert len(user1_contexts) == 2
        assert "user1:match1" in user1_contexts
        assert "user1:match2" in user1_contexts
    finally:
        Path(temp_file).unlink()


def test_storage_persistence():
    """Test that storage persists to file."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        f.write('{}')
        temp_file = f.name
    
    try:
        storage1 = ContextStorage(temp_file)
        storage1.set_context("user1", "match1", "persisted context")
        
        storage2 = ContextStorage(temp_file)
        assert storage2.get_context("user1", "match1") == "persisted context"
    finally:
        Path(temp_file).unlink()

