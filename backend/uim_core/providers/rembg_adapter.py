from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RembgResult:
    output_path: Path
    model_name: str


class RembgAdapter:
    def __init__(self, model_name: str = "isnet-general-use") -> None:
        self.model_name = model_name
        self._session = None

    def available(self) -> bool:
        try:
            import rembg  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_session(self):
        if self._session is None:
            from rembg import new_session

            self._session = new_session(self.model_name)
        return self._session

    def remove_background(self, input_path: Path, output_path: Path) -> RembgResult:
        if not self.available():
            raise RuntimeError("rembg is not installed. Install optional rembg dependencies first.")
        from rembg import remove

        session = self._get_session()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = remove(input_path.read_bytes(), session=session)
        output_path.write_bytes(result)
        return RembgResult(output_path=output_path, model_name=self.model_name)
