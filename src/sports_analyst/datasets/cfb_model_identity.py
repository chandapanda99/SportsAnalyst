"""Content identities for the installed model bundle, without importing providers."""
import hashlib
import importlib.metadata
import json
from functools import lru_cache

MODELS = ("ep_model.ubj", "wp_naive.ubj", "cfb_cp_model.ubj", "xpass_model.ubj")


@lru_cache(maxsize=4)
def model_identity(version):
    distribution = importlib.metadata.distribution("sportsdataverse")
    artifacts = {}
    for name in MODELS:
        path = distribution.locate_file(f"sportsdataverse/cfb/models/{name}")
        if not path.is_file():
            raise ValueError(f"Current CFB model artifact is unavailable: {name}")
        with path.open("rb") as stream:
            artifacts[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    digest = hashlib.sha256(json.dumps({"package": version, "artifacts": artifacts,
                                       "pipeline": "spread-free-v1"}, sort_keys=True).encode()).hexdigest()
    return f"cfb-models:{digest}"
