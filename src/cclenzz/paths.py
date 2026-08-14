from __future__ import annotations

"""Where cclenzz files live. A frozen ``AppPaths`` record replaces the old
mutable ``STATE_ROOT`` / ``PROJECTS_GLOB`` globals and ``_config_path`` /
``state_root`` helpers (§5.1). This is the sandboxing seam: tests point an
``AppPaths`` at temp dirs; production only ever uses ``default()`` + the config
``projects_glob`` override. No env var is consulted beyond what ``expanduser``
does with ``HOME`` — identical to before."""

import dataclasses
import os


@dataclasses.dataclass(frozen=True)
class AppPaths:
    state_root: str
    projects_glob: str

    @property
    def config_path(self) -> str:
        return os.path.join(self.state_root, "config.toml")

    def sessions_state_dir(self) -> str:
        return os.path.join(self.state_root, "sessions")

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(
            state_root=os.path.join(os.path.expanduser("~"), ".cclenzz"),
            projects_glob=os.path.expanduser("~/.claude/projects/*/*.jsonl"),
        )

    def with_projects_glob(self, glob_: str) -> "AppPaths":
        return dataclasses.replace(self, projects_glob=os.path.expanduser(glob_))
