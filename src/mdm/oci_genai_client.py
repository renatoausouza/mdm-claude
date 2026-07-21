import logging
from typing import Any

import oci
from oci.generative_ai import GenerativeAiClient

from mdm import config

logger = logging.getLogger(__name__)


def load_oci_sdk_config() -> dict[str, Any]:
    """Shared by every OCI Generative AI caller (this module's readiness
    check and llm_extraction.py's OciGenAiExtractionClient) so config-file
    path/profile resolution lives in exactly one place."""
    file_location = config.get_oci_config_file_path()
    kwargs: dict[str, Any] = {"profile_name": config.get_oci_config_profile()}
    if file_location:
        kwargs["file_location"] = file_location
    result: dict[str, Any] = oci.config.from_file(**kwargs)
    return result


class OciGenAiClient:
    def check(self) -> bool:
        """Readiness probe: list_models is a control-plane read — it proves
        auth/network reachability to OCI Generative AI without invoking (and
        paying for) an actual model completion, mirroring how the previous
        Ollama check used a 1-token ping instead of a real extraction call."""
        try:
            oci_config = load_oci_sdk_config()
            compartment_id = config.get_oci_genai_compartment_id()
            client = GenerativeAiClient(oci_config)
            client.list_models(compartment_id=compartment_id, limit=1)
            return True
        except Exception as exc:
            # Deliberately broad: a missing config file, a bad profile, an
            # unset compartment env var, or a genuine network/auth failure
            # should all report "not ready", not crash the /ready endpoint —
            # there's no single narrow exception type covering all of them
            # the way httpx.HTTPError did for the old local HTTP-only check.
            logger.warning("OCI Generative AI readiness check failed: %s", exc)
            return False
