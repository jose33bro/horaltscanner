"""API module entrypoint.

Run as a module from the ``software/`` directory:

    python3 -m api.app

or via systemd with ``WorkingDirectory=/home/pi/horaltscanner/software`` and
``ExecStart=... python3 -m api.app``.
"""

from api import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
