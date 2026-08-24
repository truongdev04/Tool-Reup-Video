"""Storage layout — docs §12, retention §17.2.

LỆCH KHỎI KẾ HOẠCH §12 (có chủ ý):
    §12 vẽ layout phẳng theo project (`/projects/{id}/tts`, `/translation`...).
    Nhưng một source video sinh ra NHIỀU job, mỗi job một locale, và các artifact
    đó tách biệt nhau. Layout phẳng sẽ khiến bản ES và bản JA ghi đè lên nhau.

    Nên: artifact KHÔNG phụ thuộc locale nằm ở cấp project (source, analysis,
    separated, transcript — dùng chung, đúng tinh thần cache §16); artifact
    phụ thuộc locale nằm dưới `jobs/{job_id}/`.
"""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from core.types import ArtifactKind

#: Retention theo loại artifact (§17.2). None = giữ tới khi xoá project.
RETENTION_DAYS: dict[ArtifactKind, int | None] = {
    ArtifactKind.SOURCE: None,
    ArtifactKind.ANALYSIS: None,
    ArtifactKind.TRANSCRIPT: None,
    ArtifactKind.TRANSLATION: None,
    ArtifactKind.SEPARATED: 30,
    ArtifactKind.COMPOSED: 30,
    ArtifactKind.TTS: 30,
    ArtifactKind.ASSEMBLED: 30,
    ArtifactKind.SUBTITLE: None,
    ArtifactKind.PREVIEW: 7,
    ArtifactKind.FINAL: None,
}

#: Artifact dùng chung giữa mọi locale của cùng một source.
_PROJECT_LEVEL = {
    ArtifactKind.SOURCE: Path("source"),
    ArtifactKind.ANALYSIS: Path("analysis"),
    ArtifactKind.SEPARATED: Path("audio/separated"),
    ArtifactKind.COMPOSED: Path("composed"),
    ArtifactKind.TRANSCRIPT: Path("transcript"),
}

#: Artifact riêng theo locale.
_JOB_LEVEL = {
    ArtifactKind.TRANSLATION: Path("translation"),
    ArtifactKind.TTS: Path("audio/tts"),
    ArtifactKind.ASSEMBLED: Path("audio/assembled"),
    ArtifactKind.SUBTITLE: Path("subtitle"),
    ArtifactKind.PREVIEW: Path("preview"),
    ArtifactKind.FINAL: Path("final"),
}


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else get_settings().storage_root

    def project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def job_dir(self, project_id: str, job_id: str) -> Path:
        return self.project_dir(project_id) / "jobs" / job_id

    def path_for(
        self,
        kind: ArtifactKind,
        *,
        project_id: str,
        job_id: str | None = None,
        filename: str = "",
    ) -> Path:
        """Đường dẫn cho một artifact. Tạo sẵn thư mục cha."""
        if kind in _PROJECT_LEVEL:
            base = self.project_dir(project_id) / _PROJECT_LEVEL[kind]
        elif kind in _JOB_LEVEL:
            if job_id is None:
                raise ValueError(f"artifact {kind} phụ thuộc locale nên bắt buộc có job_id")
            base = self.job_dir(project_id, job_id) / _JOB_LEVEL[kind]
        else:
            raise ValueError(f"chưa khai báo vị trí lưu cho artifact kind: {kind}")

        base.mkdir(parents=True, exist_ok=True)
        return base / filename if filename else base

    def tts_chunk_path(self, *, project_id: str, job_id: str, unit_idx: int, chunk_idx: int) -> Path:
        """Mỗi chunk TTS là một file riêng có địa chỉ — điều kiện của partial
        re-run (§6.9, §11.3)."""
        return self.path_for(
            ArtifactKind.TTS,
            project_id=project_id,
            job_id=job_id,
            filename=f"u{unit_idx:05d}_c{chunk_idx:03d}.wav",
        )

    def relative(self, path: Path) -> str:
        """Lưu đường dẫn tương đối vào DB để di chuyển storage không hỏng dữ liệu."""
        try:
            return str(Path(path).resolve().relative_to(self.root))
        except ValueError:
            return str(path)
