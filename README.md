# OpenMemory FastMCP Server with Tailscale Integration

A FastMCP-based implementation of the OpenMemory server that replaces SSE (Server-Sent Events) with HTTP streaming transport, deployed as a Docker container with Tailscale network integration.

## Overview

This project reimplements the mem0 OpenMemory MCP server using FastMCP's HTTP streaming transport, providing:

- **HTTP Streaming**: More reliable than SSE with better browser and proxy support
- **Tailscale Integration**: Secure remote access without port forwarding
- **Docker Deployment**: Easy containerized deployment with all dependencies
- **Full mem0 Compatibility**: All memory management features preserved

## Features

- ✅ Add memories with automatic categorization
- ✅ Search memories using vector similarity
- ✅ List all user memories with permission filtering  
- ✅ Delete memories with audit logging
- ✅ Multi-tenancy support (users and apps)
- ✅ Qdrant vector database integration
- ✅ Support for OpenAI, Anthropic, and Ollama models

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│   MCP Client    │────▶│  Tailscale Net   │
└─────────────────┘     └──────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  OpenMemory Server  │
                    │   (FastMCP HTTP)    │
                    └─────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
            ┌──────────────┐      ┌──────────────┐
            │   Qdrant     │      │   SQLite     │
            │ Vector Store │      │   Database   │
            └──────────────┘      └──────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Tailscale account (for remote access)
- OpenAI API key (or Anthropic API key)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/artur-nohup/openmemory-fastmcp.git
cd openmemory-fastmcp
```

2. Create environment file:
```bash
cp .env.example .env
# Edit .env with your API keys and Tailscale auth key
```

3. Deploy the server:
```bash
./scripts/deploy.sh
```

## Connection Methods

### Local Access
```python
from fastmcp import Client

async with Client("http://localhost:8765/mcp") as client:
    await client.call_tool("add_memories", {
        "text": "I prefer dark mode",
        "user_id": "john_doe",
        "client_name": "my_app"
    })
```

### Tailscale Access
```python
# From anywhere in your Tailscale network
async with Client("http://openmemory-server:8765/mcp") as client:
    # Same API as local access
    ...
```

## MCP Tools

### `add_memories`
Add new memories to the system.

**Arguments:**
- `text` (str): The text to remember
- `user_id` (str, optional): User identifier
- `client_name` (str, optional): Application identifier

### `search_memory`
Search through stored memories using semantic similarity.

### `list_memories`
List all memories for a user.

### `delete_all_memories`
Delete all accessible memories for a user.

## Testing

Run the test suite:
```bash
python testing/test_comprehensive.py
```

## Monitoring

```bash
# View all services
docker-compose ps

# View logs
docker logs openmemory-fastmcp
```

## License

This project is based on the mem0 OpenMemory implementation.

## Acknowledgments

- [mem0ai](https://github.com/mem0ai/mem0) for the original OpenMemory implementation
- [FastMCP](https://github.com/jlowin/fastmcp) for the improved MCP framework
- [Tailscale](https://tailscale.com) for secure networking

🤖 Generated with [Claude Code](https://claude.ai/code)