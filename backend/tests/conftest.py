import os
import tempfile

# Must run before `app` is imported: the DB engine is created from settings at import time.
os.environ["TGT_DATA_DIR"] = tempfile.mkdtemp(prefix="tgt-test-")
os.environ["TGT_SCHEDULER_ENABLED"] = "false"
