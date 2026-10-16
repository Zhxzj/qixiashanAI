"""Separate connection pools shared for the application lifespan."""
import httpx
class Provider:
    chat = media = weather = None
    async def start(self):
        self.chat = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15), limits=httpx.Limits(max_connections=12, max_keepalive_connections=8))
        self.media = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        self.weather = httpx.AsyncClient(timeout=httpx.Timeout(8, connect=6), limits=httpx.Limits(max_connections=4))
    async def close(self):
        for client in (self.chat, self.media, self.weather):
            if client:
                await client.aclose()
