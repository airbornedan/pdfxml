from app import create_app
from app.extensions import PORT

app = create_app()

if __name__ == "__main__":
    ### debug=True would show Werkzeug's interactive debugger on any
    ### unhandled exception (arbitrary code execution from the browser)
    ### and bypass the registered error handlers -- off, always.
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=True)
