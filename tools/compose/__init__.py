"""Dev-only procedural composer for Showreel's shipped music beds and SFX kit.

Run from the repo root with the dev venv (numpy + scipy):
    python -m tools.compose --all              # every bed + the SFX kit (reproducible from seeds)
    python -m tools.compose --beds launch_a    # one bed
    python -m tools.compose --sfx              # SFX kit only
Nothing here is imported by the plugin at runtime; outputs land in ``assets/audio``.
"""
