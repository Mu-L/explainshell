import logging
import os

from explainshell import config
from explainshell.web import create_app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        force=True,
    )

    app = create_app()
    port = int(os.environ.get("PORT", 5000))

    if config.HOST_IP:
        app.run(debug=config.DEBUG, host=config.HOST_IP, port=port)
    else:
        app.run(debug=config.DEBUG, port=port)
