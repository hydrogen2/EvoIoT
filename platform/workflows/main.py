"""Workflows service entry point."""

import restate
from classifier import classification_workflow

# Create the Restate app with all workflows
app = restate.app(services=[classification_workflow])

if __name__ == "__main__":
    import hypercorn.asyncio
    import hypercorn.config
    import asyncio

    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:9080"]

    asyncio.run(hypercorn.asyncio.serve(app, config))
