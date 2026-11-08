"""Prompts are versioned files (prompts/<id>/<version>.yaml). The version tag recorded with every
step and response is "<id>@<version>#<content hash>", so an edited file never masquerades as the
same version."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

import yaml

from .config import settings


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    system: str
    user: str
    digest: str

    @property
    def tag(self) -> str:
        return f"{self.id}@{self.version}#{self.digest}"

    def render(self, **kw) -> list[dict]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": self.user.format(**kw)}]


@lru_cache(maxsize=32)
def load(prompt_id: str, version: str) -> Prompt:
    path = os.path.join(settings().prompts_dir, prompt_id, f"{version}.yaml")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    data = yaml.safe_load(raw)
    return Prompt(data["id"], data["version"], data["system"], data["user"], hashlib.sha1(raw.encode()).hexdigest()[:8])


def active_versions(overrides: dict | None = None) -> dict:
    """Prompt tags and agent switches recorded on the run. Evaluation may override them per run."""
    s = settings()
    o = overrides or {}
    research_version = o.get("research") if o.get("research") in ("v1", "v2") else s.research_prompt_version
    gate = o.get("modifier_gate") if isinstance(o.get("modifier_gate"), bool) else s.require_modifier_search
    return {
        "intake": load("intake", s.intake_prompt_version).tag,
        "research": load("research", research_version).tag,
        "verifier": load("verifier", s.verifier_prompt_version).tag,
        "research_version": research_version,
        "modifier_gate": gate,
    }
