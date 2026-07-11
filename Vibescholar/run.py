import uvicorn
from app.app import fastapi_app

if __name__ == "__main__":
    # Start the server on port 8080. NiceGUI will automatically run on top of it.
    uvicorn.run("app.app:fastapi_app", host="127.0.0.1", port=8080, reload=False)
