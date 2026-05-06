"""Background thread for Claude character extraction."""

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.claude import extraction as claude_client
from app.keyring_store import get_anthropic_key


class ExtractionWorker(QThread):
    log = Signal(str)
    done = Signal(dict)    # result dict from claude_client.extract_character
    failed = Signal(str)   # error message

    def __init__(self, image_path, character_id=""):
        super().__init__()
        self.image_path = Path(image_path)
        self.character_id = character_id

    def run(self):
        api_key = get_anthropic_key()
        if not api_key:
            self.failed.emit("Anthropic API key not set.")
            return

        self.log.emit(f"Extracting character from {self.image_path.name}...")

        result = claude_client.extract_character(
            api_key=api_key,
            image_path=self.image_path,
            character_id=self.character_id,
        )

        if result["success"]:
            self.log.emit(
                f"  Extraction complete. "
                f"Tokens: {result['input_tokens']}in / {result['output_tokens']}out  "
                f"Cost: ${result['cost']:.4f}  "
                f"Confidence: {result['data'].get('extraction_confidence', '?')}"
            )
            self.done.emit(result)
        else:
            self.log.emit(f"  Extraction failed: {result.get('error', 'Unknown')}")
            self.failed.emit(result.get("error", "Unknown error"))
