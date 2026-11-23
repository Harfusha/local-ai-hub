from __future__ import annotations

# Keep module globals patchable while repo_tools methods live in mixins.
# ruff: noqa: F401

import os
import stat
import subprocess
import sys
import threading
import time
import types
from typing import Any

from .budget import chars_for_tokens, estimate_tokens
from .process_utils import canonical_root, hidden_run_kwargs, popen_managed, run_hidden, terminate_tree

from .repo_tools_constants import (
    MAX_EXACT_GIT_PATH_BYTES,
    MAX_EXACT_GIT_PATHS,
    MAX_EXACT_SEARCH_FILES,
    _HARD_SEARCH_DIRS,
    _IMPACT_RIPGREP_TIMEOUT_SECONDS,
    _IMPACT_SCAN_MAX_FILES,
    _IMPACT_SCAN_TIMEOUT_SECONDS,
    _INSTALLATION_INTENT_TERMS,
    _MAX_DIRECTORY_HINT_FILES,
    _MAX_PATH_CONTROLS,
    _SYMBOL_PATTERNS,
    _UNSET_GIT_INVENTORY,
    _WORD,
)
from .repo_tools_models import (
    FileTooLargeError,
    GitBlobRecord,
    GitFileInventory,
    GitSnapshot,
    _BoundedSortedPaths,
    _IncompleteGitInventory,
    _ReversePath,
)
from .repo_tools_path_helpers import (
    _intent_path_adjustment,
    _intent_query_terms,
    _is_installation_intent,
    _lower_expansion_characters,
    _record_security_inventory_issue,
    _unicode_lower_expansions,
    _windows_file_api,
    is_root_archive_path,
)

from . import repo_tools_constants as _repo_tools_constants
from . import repo_tools_models as _repo_tools_models
from . import repo_tools_path_helpers as _repo_tools_path_helpers

from . import repo_tools_inventory as _repo_tools_inventory
from .repo_tools_inventory import RepoToolsInventoryMixin
from . import repo_tools_search_backend as _repo_tools_search_backend
from .repo_tools_search_backend import RepoToolsSearchBackendMixin
from . import repo_tools_project_search as _repo_tools_project_search
from .repo_tools_project_search import RepoToolsProjectSearchMixin
from . import repo_tools_workspace as _repo_tools_workspace
from .repo_tools_workspace import RepoToolsWorkspaceMixin
from . import repo_tools_context as _repo_tools_context
from .repo_tools_context import RepoToolsContextMixin
from . import repo_tools_patch as _repo_tools_patch
from .repo_tools_patch import RepoToolsPatchMixin
from . import repo_tools_files as _repo_tools_files
from .repo_tools_files import RepoToolsFilesMixin


class RepositoryTools(
    RepoToolsInventoryMixin,
    RepoToolsSearchBackendMixin,
    RepoToolsProjectSearchMixin,
    RepoToolsWorkspaceMixin,
    RepoToolsContextMixin,
    RepoToolsPatchMixin,
    RepoToolsFilesMixin,
):
    pass


for _repo_tools_module in (
    _repo_tools_inventory,
    _repo_tools_search_backend,
    _repo_tools_project_search,
    _repo_tools_workspace,
    _repo_tools_context,
    _repo_tools_patch,
    _repo_tools_files,
):
    _repo_tools_module.RepositoryTools = RepositoryTools


class _RepositoryToolsModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (
            _repo_tools_constants,
            _repo_tools_models,
            _repo_tools_path_helpers,
            _repo_tools_inventory,
            _repo_tools_search_backend,
            _repo_tools_project_search,
            _repo_tools_workspace,
            _repo_tools_context,
            _repo_tools_patch,
            _repo_tools_files,
        ):
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _RepositoryToolsModuleProxy


__all__ = [
    'Any',
    'FileTooLargeError',
    'GitBlobRecord',
    'GitFileInventory',
    'GitSnapshot',
    'MAX_EXACT_GIT_PATHS',
    'MAX_EXACT_GIT_PATH_BYTES',
    'MAX_EXACT_SEARCH_FILES',
    'RepoToolsContextMixin',
    'RepoToolsFilesMixin',
    'RepoToolsInventoryMixin',
    'RepoToolsPatchMixin',
    'RepoToolsProjectSearchMixin',
    'RepoToolsSearchBackendMixin',
    'RepoToolsWorkspaceMixin',
    'RepositoryTools',
    '_BoundedSortedPaths',
    '_HARD_SEARCH_DIRS',
    '_IMPACT_RIPGREP_TIMEOUT_SECONDS',
    '_IMPACT_SCAN_MAX_FILES',
    '_IMPACT_SCAN_TIMEOUT_SECONDS',
    '_INSTALLATION_INTENT_TERMS',
    '_IncompleteGitInventory',
    '_MAX_DIRECTORY_HINT_FILES',
    '_MAX_PATH_CONTROLS',
    '_RepositoryToolsModuleProxy',
    '_ReversePath',
    '_SYMBOL_PATTERNS',
    '_UNSET_GIT_INVENTORY',
    '_WORD',
    '_intent_path_adjustment',
    '_intent_query_terms',
    '_is_installation_intent',
    '_lower_expansion_characters',
    '_record_security_inventory_issue',
    '_repo_tools_constants',
    '_repo_tools_context',
    '_repo_tools_files',
    '_repo_tools_inventory',
    '_repo_tools_models',
    '_repo_tools_patch',
    '_repo_tools_path_helpers',
    '_repo_tools_project_search',
    '_repo_tools_search_backend',
    '_repo_tools_workspace',
    '_unicode_lower_expansions',
    '_windows_file_api',
    'annotations',
    'canonical_root',
    'chars_for_tokens',
    'estimate_tokens',
    'hidden_run_kwargs',
    'is_root_archive_path',
    'os',
    'popen_managed',
    'run_hidden',
    'stat',
    'subprocess',
    'sys',
    'terminate_tree',
    'threading',
    'time',
    'types',
]
