
from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from models import DailyReport


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _human_name_from_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    name = p.rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = name.strip()
    if not name:
        return ""
    if len(name) > 40:
        return ""
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in name):
        return ""
    return name


def _infer_descriptive_points(repo) -> list[str]:
    points: list[str] = []

    commit_details = getattr(repo, "commit_details", None) or []
    for detail in commit_details:
        message = _normalize(str(detail.get("message", "")))
        files = detail.get("files") or []
        file_paths = [str(p) for p in files if str(p).strip()]

        has_page = any(
            "/pages/" in p
            or p.endswith("Page.tsx")
            or p.endswith(".vue")
            or "/page/" in p
            for p in file_paths
        )
        has_components = any("/components/" in p for p in file_paths)
        has_backend = any(
            any(k in _normalize(p) for k in ["controller", "route", "routes", "api", "endpoint"])
            for p in file_paths
        )
        has_service = any(
            any(k in _normalize(p) for k in ["service", "repository"]) for p in file_paths
        )
        has_db = any(
            any(k in _normalize(p) for k in ["migration", "schema"]) for p in file_paths
        )

        if has_page:
            name = ""
            for p in file_paths:
                if "/pages/" in p or p.endswith("Page.tsx"):
                    name = _human_name_from_path(p)
                    if name:
                        break
            points.append(
                f"Membuat atau mengubah halaman {name}" if name else "Membuat atau mengubah halaman"
            )

        if has_components:
            name = ""
            for p in file_paths:
                if "/components/" in p:
                    name = _human_name_from_path(p)
                    if name:
                        break
            points.append(
                f"Mengembangkan atau memperbarui komponen UI {name}"
                if name
                else "Mengembangkan atau memperbarui komponen UI"
            )

        if has_backend:
            points.append("Menambahkan atau mengubah logic backend / endpoint")

        if has_service:
            points.append("Mengubah layer service atau business logic")

        if has_db:
            points.append("Mengubah struktur database")

        if message.startswith("feat"):
            points.append("Menambahkan fitur baru")
        elif message.startswith("fix"):
            points.append("Melakukan perbaikan bug")
        elif message.startswith("refactor"):
            points.append("Melakukan refactoring kode")
        elif message.startswith("chore"):
            points.append("Melakukan maintenance")

    seen: set[str] = set()
    out: list[str] = []
    for p in points:
        p = (p or "").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _load_ai_client():
    mod_path = Path(__file__).resolve().parent / "llm-client.py"
    spec = spec_from_file_location("dev_memory_llm_client", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load llm-client.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_daily_narrative(report: DailyReport) -> str:
    report_data = report.model_dump() if hasattr(report, "model_dump") else report.__dict__
    prompt = "\n".join(
        [
            "Kamu adalah Software Engineer senior yang sedang menulis laporan profesional.",
            "",
            "Gunakan hanya data terstruktur berikut.",
            json.dumps(report_data, indent=2),
            "",
            "Tulis output dalam Bahasa Indonesia:",
            "- 1 paragraf ringkasan eksekutif",
            "- Daftar bullet kontribusi utama",
            "- Pernyataan jelas pekerjaan yang dibawa (carry-over)",
            "- Dampak pekerjaan",
            "- Area teknis yang disentuh",
            "- Fokus berikutnya",
            "",
            "Aturan:",
            "- Jangan mengarang metrik",
            "- Jangan melebih-lebihkan",
            "- Jangan halusinasi",
            "- Gunakan hanya data yang diberikan",
        ]
    )

    client = _load_ai_client()
    return client.generate_ai_summary(prompt)


def generate_markdown(report: DailyReport, include_ai: bool = False) -> str:
    parts: list[str] = []

    date_str = getattr(report, "date", "")
    parts.append(f"# Laporan Harian — {date_str}")
    parts.append("")

    if getattr(report, "status", None) == "no_activity":
        parts.append("Tidak ada aktivitas development yang terdeteksi.")
        parts.append("")
        return "\n".join(parts)

    committed = getattr(report, "committed", None) or []
    total_commits = sum(getattr(x, "commits_count", 0) for x in committed)
    total_files_changed = sum(getattr(x, "files_changed", 0) for x in committed)

    parts.append("## Ringkasan")
    parts.append(f"- Repository yang dikerjakan: {getattr(report, 'repos_touched', 0)}")
    parts.append(f"- Total commit: {total_commits}")
    parts.append(f"- Total file berubah: {total_files_changed}")
    parts.append("")
    parts.append("---")
    parts.append("")

    parts.append("## Rincian Per Repository")
    parts.append("")

    for repo in committed:
        parts.append(f"### {getattr(repo, 'repo_name', '')}")
        parts.append(f"Cabang: {getattr(repo, 'branch', '')}  ")
        parts.append(f"Jumlah Commit: {getattr(repo, 'commits_count', 0)}  ")
        parts.append(f"File Berubah: {getattr(repo, 'files_changed', 0)}  ")
        parts.append(f"Penambahan Baris: {getattr(repo, 'insertions', 0)}  ")
        parts.append(f"Pengurangan Baris: {getattr(repo, 'deletions', 0)}  ")
        parts.append(f"Jenis Aktivitas: {getattr(repo, 'activity_type', 'improvement')}  ")

        descriptive_points = _infer_descriptive_points(repo)
        if descriptive_points:
            parts.append("Poin Pekerjaan:")
            for p in descriptive_points:
                parts.append(f"- {p}")
        parts.append("")

    parts.append("---")
    parts.append("")

    working_state = getattr(report, "working_state", None) or []
    if working_state:
        parts.append("## Pekerjaan Belum Di-Commit (Carry Over)")
        parts.append("")
        for ws in working_state:
            parts.append(f"### {getattr(ws, 'repo_name', '')}")
            parts.append(f"Cabang: {getattr(ws, 'branch', '')}  ")
            parts.append("File yang Dimodifikasi:")
            for path in (getattr(ws, "modified_files", None) or []):
                parts.append(f"- {path}")
            parts.append("")

        parts.append("---")
        parts.append("")

    parts.append("## Template Standup")
    parts.append("")
    parts.append("Kemarin:")
    for repo in committed:
        repo_name = getattr(repo, "repo_name", "")
        descriptive_points = _infer_descriptive_points(repo)
        if descriptive_points:
            for p in descriptive_points:
                parts.append(f"- {p} ({repo_name})")
        else:
            parts.append(
                f"- Mengerjakan {repo_name} ({getattr(repo, 'activity_type', 'improvement')})"
            )
    if not committed:
        parts.append("- Tidak ada pekerjaan yang di-commit")
    parts.append("")

    parts.append("Hari ini:")
    if working_state:
        seen: set[str] = set()
        for ws in working_state:
            repo_name = getattr(ws, "repo_name", "")
            if repo_name in seen:
                continue
            seen.add(repo_name)
            parts.append(f"- Melanjutkan pekerjaan yang belum di-commit pada {repo_name}")
    else:
        parts.append("- Melanjutkan pengembangan fitur")
    parts.append("")

    parts.append("Hambatan:")
    parts.append("- Tidak ada")
    parts.append("")

    if include_ai:
        try:
            narrative = generate_daily_narrative(report)
        except Exception as e:
            print(f"Warning: AI narrative generation failed: {e}")
            narrative = ""

        if narrative.strip():
            parts.append("---")
            parts.append("")
            parts.append("## Ringkasan Naratif AI")
            parts.append("")
            parts.append(narrative.strip())
            parts.append("")

    return "\n".join(parts)
