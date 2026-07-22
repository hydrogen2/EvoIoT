"""Workflows service entry point."""

import restate
from classifier import classification_workflow
from discovery import equipment_discovery_workflow
from extraction import file_extraction_workflow
from watcher import file_watcher
from collectors import collector
from netdisco import device_discovery_workflow

# Create the Restate app with all workflows
app = restate.app(services=[classification_workflow, equipment_discovery_workflow,
                            file_extraction_workflow, file_watcher, collector,
                            device_discovery_workflow])

if __name__ == "__main__":
    import hypercorn.asyncio
    import hypercorn.config
    import asyncio

    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:9080"]

    asyncio.run(hypercorn.asyncio.serve(app, config))
