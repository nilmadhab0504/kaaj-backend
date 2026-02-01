"""
Run the API server on port 3005.
Usage: python3 run.py   (from backend directory)
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3005,
        reload=True,
    )
