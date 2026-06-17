import uvicorn
import asyncio
import sys

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Debug: Print the policy
    print(f"DEBUG: Event loop policy set to: {asyncio.get_event_loop_policy().__class__.__name__}")
    
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, loop="asyncio")
