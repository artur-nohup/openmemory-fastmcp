#!/usr/bin/env python3
"""
OpenMemory FastMCP Server - Standalone Implementation
"""

import logging
import json
import uuid
import datetime
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from qdrant_client import models as qdrant_models

from models import (
    SessionLocal, Memory, MemoryState, MemoryStatusHistory, 
    MemoryAccessLog, User, App
)
from memory_utils import (
    get_memory_client_safe, get_user_and_app, 
    check_memory_access_permissions
)
from config import DEFAULT_USER_ID, DEFAULT_CLIENT_NAME

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("openmemory-server")

@asynccontextmanager
async def get_db():
    """Database session context manager"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@mcp.tool
async def add_memories(text: str, user_id: str = None, client_name: str = None) -> str:
    """
    Add a new memory. This method is called everytime the user informs anything 
    about themselves, their preferences, or anything that has any relevant 
    information which can be useful in the future conversation.
    
    Args:
        text: The text content to remember
        user_id: The user ID (optional, defaults to 'default_user')
        client_name: The client/app name (optional, defaults to 'default_app')
    
    Returns:
        JSON response with the added memory details
    """
    # Use defaults if not provided
    user_id = user_id or DEFAULT_USER_ID
    client_name = client_name or DEFAULT_CLIENT_NAME
    
    # Get memory client safely
    memory_client = get_memory_client_safe()
    if not memory_client:
        return json.dumps({"error": "Memory system is currently unavailable. Please try again later."})
    
    try:
        async with get_db() as db:
            # Get or create user and app
            user, app = get_user_and_app(db, user_id=user_id, app_id=client_name)
            
            # Check if app is active
            if not app.is_active:
                return json.dumps({"error": f"App {app.name} is currently paused on OpenMemory. Cannot create new memories."})
            
            response = memory_client.add(
                text,
                user_id=user_id,
                metadata={
                    "source_app": "openmemory",
                    "mcp_client": client_name,
                }
            )
            
            # Process the response and update database
            if isinstance(response, dict) and 'results' in response:
                for result in response['results']:
                    memory_id = uuid.UUID(result['id'])
                    memory = db.query(Memory).filter(Memory.id == memory_id).first()
                    
                    if result['event'] == 'ADD':
                        if not memory:
                            memory = Memory(
                                id=memory_id,
                                user_id=user.id,
                                app_id=app.id,
                                content=result['memory'],
                                state=MemoryState.active
                            )
                            db.add(memory)
                        else:
                            memory.state = MemoryState.active
                            memory.content = result['memory']
                        
                        # Create history entry
                        history = MemoryStatusHistory(
                            memory_id=memory_id,
                            changed_by=user.id,
                            old_state=MemoryState.deleted if memory else None,
                            new_state=MemoryState.active
                        )
                        db.add(history)
                    
                    elif result['event'] == 'DELETE':
                        if memory:
                            memory.state = MemoryState.deleted
                            memory.deleted_at = datetime.datetime.now(datetime.UTC)
                            # Create history entry
                            history = MemoryStatusHistory(
                                memory_id=memory_id,
                                changed_by=user.id,
                                old_state=MemoryState.active,
                                new_state=MemoryState.deleted
                            )
                            db.add(history)
                
                db.commit()
            
            return json.dumps(response)
    except Exception as e:
        logger.exception(f"Error adding to memory: {e}")
        return json.dumps({"error": f"Error adding to memory: {str(e)}"})


@mcp.tool
async def search_memory(query: str, user_id: str = None, client_name: str = None) -> str:
    """
    Search through stored memories. This method is called EVERYTIME the user asks anything.
    
    Args:
        query: The search query
        user_id: The user ID (optional, defaults to 'default_user')
        client_name: The client/app name (optional, defaults to 'default_app')
    
    Returns:
        JSON array of matching memories with scores
    """
    # Use defaults if not provided
    user_id = user_id or DEFAULT_USER_ID
    client_name = client_name or DEFAULT_CLIENT_NAME
    
    # Get memory client safely
    memory_client = get_memory_client_safe()
    if not memory_client:
        return json.dumps({"error": "Memory system is currently unavailable. Please try again later."})
    
    try:
        async with get_db() as db:
            # Get or create user and app
            user, app = get_user_and_app(db, user_id=user_id, app_id=client_name)
            
            # Get accessible memory IDs based on ACL
            user_memories = db.query(Memory).filter(Memory.user_id == user.id).all()
            accessible_memory_ids = [
                memory.id for memory in user_memories 
                if check_memory_access_permissions(db, memory, app.id)
            ]
            
            conditions = [
                qdrant_models.FieldCondition(
                    key="user_id", 
                    match=qdrant_models.MatchValue(value=user_id)
                )
            ]
            
            if accessible_memory_ids:
                # Convert UUIDs to strings for Qdrant
                accessible_memory_ids_str = [str(memory_id) for memory_id in accessible_memory_ids]
                conditions.append(
                    qdrant_models.HasIdCondition(has_id=accessible_memory_ids_str)
                )
            
            filters = qdrant_models.Filter(must=conditions)
            embeddings = memory_client.embedding_model.embed(query, "search")
            
            hits = memory_client.vector_store.client.query_points(
                collection_name=memory_client.vector_store.collection_name,
                query=embeddings,
                query_filter=filters,
                limit=10,
            )
            
            # Process search results
            memories = hits.points
            memories = [
                {
                    "id": memory.id,
                    "memory": memory.payload["data"],
                    "hash": memory.payload.get("hash"),
                    "created_at": memory.payload.get("created_at"),
                    "updated_at": memory.payload.get("updated_at"),
                    "score": memory.score,
                }
                for memory in memories
            ]
            
            # Log memory access for each memory found
            for memory in memories:
                memory_id = uuid.UUID(memory['id'])
                # Create access log entry
                access_log = MemoryAccessLog(
                    memory_id=memory_id,
                    app_id=app.id,
                    access_type="search",
                    metadata_={
                        "query": query,
                        "score": memory.get('score'),
                        "hash": memory.get('hash')
                    }
                )
                db.add(access_log)
            db.commit()
            
            return json.dumps(memories)
    except Exception as e:
        logger.exception(f"Error searching memory: {e}")
        return json.dumps({"error": f"Error searching memory: {str(e)}"})


@mcp.tool
async def list_memories(user_id: str = None, client_name: str = None) -> str:
    """
    List all memories in the user's memory
    
    Args:
        user_id: The user ID (optional, defaults to 'default_user')
        client_name: The client/app name (optional, defaults to 'default_app')
    
    Returns:
        JSON array of all accessible memories
    """
    # Use defaults if not provided
    user_id = user_id or DEFAULT_USER_ID
    client_name = client_name or DEFAULT_CLIENT_NAME
    
    # Get memory client safely
    memory_client = get_memory_client_safe()
    if not memory_client:
        return json.dumps({"error": "Memory system is currently unavailable. Please try again later."})
    
    try:
        async with get_db() as db:
            # Get or create user and app
            user, app = get_user_and_app(db, user_id=user_id, app_id=client_name)
            
            # Get all memories
            memories = memory_client.get_all(user_id=user_id)
            filtered_memories = []
            
            # Filter memories based on permissions
            user_memories = db.query(Memory).filter(Memory.user_id == user.id).all()
            accessible_memory_ids = [
                memory.id for memory in user_memories 
                if check_memory_access_permissions(db, memory, app.id)
            ]
            
            if isinstance(memories, dict) and 'results' in memories:
                memories_list = memories['results']
            else:
                memories_list = memories if isinstance(memories, list) else []
            
            for memory in memories_list:
                memory_id = uuid.UUID(memory['id'])
                if memory_id in accessible_memory_ids:
                    # Create access log entry
                    access_log = MemoryAccessLog(
                        memory_id=memory_id,
                        app_id=app.id,
                        access_type="list",
                        metadata_={
                            "hash": memory.get('hash')
                        }
                    )
                    db.add(access_log)
                    filtered_memories.append(memory)
            db.commit()
            
            return json.dumps(filtered_memories)
    except Exception as e:
        logger.exception(f"Error getting memories: {e}")
        return json.dumps({"error": f"Error getting memories: {str(e)}"})


@mcp.tool
async def delete_all_memories(user_id: str = None, client_name: str = None) -> str:
    """
    Delete all memories in the user's memory
    
    Args:
        user_id: The user ID (optional, defaults to 'default_user')
        client_name: The client/app name (optional, defaults to 'default_app')
    
    Returns:
        Success message or error
    """
    # Use defaults if not provided
    user_id = user_id or DEFAULT_USER_ID
    client_name = client_name or DEFAULT_CLIENT_NAME
    
    # Get memory client safely
    memory_client = get_memory_client_safe()
    if not memory_client:
        return json.dumps({"error": "Memory system is currently unavailable. Please try again later."})
    
    try:
        async with get_db() as db:
            # Get or create user and app
            user, app = get_user_and_app(db, user_id=user_id, app_id=client_name)
            
            user_memories = db.query(Memory).filter(Memory.user_id == user.id).all()
            accessible_memory_ids = [
                memory.id for memory in user_memories 
                if check_memory_access_permissions(db, memory, app.id)
            ]
            
            # Delete the accessible memories only
            for memory_id in accessible_memory_ids:
                try:
                    memory_client.delete(memory_id)
                except Exception as delete_error:
                    logger.warning(f"Failed to delete memory {memory_id} from vector store: {delete_error}")
            
            # Update each memory's state and create history entries
            now = datetime.datetime.now(datetime.UTC)
            for memory_id in accessible_memory_ids:
                memory = db.query(Memory).filter(Memory.id == memory_id).first()
                # Update memory state
                memory.state = MemoryState.deleted
                memory.deleted_at = now
                
                # Create history entry
                history = MemoryStatusHistory(
                    memory_id=memory_id,
                    changed_by=user.id,
                    old_state=MemoryState.active,
                    new_state=MemoryState.deleted
                )
                db.add(history)
                
                # Create access log entry
                access_log = MemoryAccessLog(
                    memory_id=memory_id,
                    app_id=app.id,
                    access_type="delete_all",
                    metadata_={"operation": "bulk_delete"}
                )
                db.add(access_log)
            
            db.commit()
            return json.dumps({"message": "Successfully deleted all memories"})
    except Exception as e:
        logger.exception(f"Error deleting memories: {e}")
        return json.dumps({"error": f"Error deleting memories: {str(e)}"})


def create_default_user_and_app():
    """Create default user and app if they don't exist"""
    db = SessionLocal()
    try:
        # Check if default user exists
        default_user = db.query(User).filter(User.user_id == DEFAULT_USER_ID).first()
        if not default_user:
            default_user = User(
                user_id=DEFAULT_USER_ID,
                name="Default User",
                email="default@openmemory.ai"
            )
            db.add(default_user)
            db.commit()
            logger.info("Created default user")
        
        # Check if default app exists
        default_app = db.query(App).filter(
            App.owner_id == default_user.id,
            App.name == DEFAULT_CLIENT_NAME
        ).first()
        if not default_app:
            default_app = App(
                owner_id=default_user.id,
                name=DEFAULT_CLIENT_NAME,
                description="Default OpenMemory Application",
                is_active=True
            )
            db.add(default_app)
            db.commit()
            logger.info("Created default app")
    finally:
        db.close()


# Create the FastMCP app with HTTP streaming
app = mcp.http_app()

# Add health check endpoint
from starlette.responses import JSONResponse
from starlette.routing import Route

async def health_check(request):
    """Health check endpoint"""
    return JSONResponse({"status": "healthy", "service": "openmemory-fastmcp"})

# Add the health route to the app
app.routes.append(Route("/health", health_check, methods=["GET"]))


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create default user and app
    create_default_user_and_app()
    
    logger.info(f"Starting OpenMemory FastMCP server on {HOST}:{PORT}")
    
    # Run the server with the HTTP app transport
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=PORT
    )