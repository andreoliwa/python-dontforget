"""Toggl plugin.

Following suggestions from https://github.com/toggl/toggl_api_docs#python:

https://github.com/AuHau/toggl-cli is a no-go, I'm really annoyed by many failed attempts.
For starters, it doesn't work with `poetry`: https://github.com/python-poetry/poetry/issues/2372
I tried installing it manually with `pip`, then `poetry install`.
Why is it loading the CLI if I'm using the API wrapper?

File "~/Library/Caches/pypoetry/virtualenvs/dontforget-KBL7kC6p-py3.7/lib/python3.7/site-packages/toggl/cli/commands.py", line 49, in <module>
    @click.group(cls=utils.SubCommandsGroup)
AttributeError: module 'toggl.utils' has no attribute 'SubCommandsGroup'

Caching attempts:

1. https://github.com/scidam/cachepy (last commit: 27.06.2019)
   There is a FileCache class, but it doesn't work between executions.
   It raises UserWarning: The file already exists. Its content will be overwritten.

```python
from cachepy import FileCache

cached_entries = FileCache("mycache", ttl=600)


@cached_entries
def fetch_entries(self) -> Dict[str, TogglEntry]:
    pass
```

2. https://github.com/bofm/python-caching (last commit 03.10.2018)
   Same problem: cache file is overwritten on every execution

```python
@Cache(ttl=600, filepath="/tmp/mycache")
def fetch_entries(self) -> Dict[str, TogglEntry]:
    pass
```

Memory-only, no file based cache:

3. https://github.com/tkem/cachetools
4. https://github.com/dgilland/cacheout

Requests only (this Toggl module uses urllib...):

5. https://github.com/reclosedev/requests-cache
6. https://github.com/ionrock/cachecontrol
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import click
import keyring
import maya
import vcr
from clib.files import fzf
from click import ClickException
from rumps import MenuItem
from toggl.TogglPy import Toggl
from vcr.persisters.filesystem import FilesystemPersister

from dontforget.app import DontForgetApp
from dontforget.plugins.base import BasePlugin
from dontforget.settings import DEFAULT_DIRS, LOG_LEVEL, load_config_file

KEYRING_API_TOKEN = "api_token"
CACHE_EXPIRATION_SECONDS = 60 * 60

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

my_vcr = vcr.VCR()


class ExpiredCassettePersister(FilesystemPersister):
    """Expired cassette persister."""

    @classmethod
    def load_cassette(cls, cassette_path, serializer):
        """Load the cassette if it's within the expected TTL."""
        path = Path(cassette_path)
        if path.exists():
            file_stat = path.stat()
            delta = datetime.now() - datetime.fromtimestamp(file_stat.st_mtime)
            if delta.total_seconds() > CACHE_EXPIRATION_SECONDS:
                raise ValueError("TTL expired, recreating the cassette")
        return super().load_cassette(cassette_path, serializer)

    @classmethod
    def save_cassette(cls, cassette_path, cassette_dict, serializer):
        """Save the cassette."""
        super().save_cassette(cassette_path, cassette_dict, serializer)


my_vcr.register_persister(ExpiredCassettePersister)


@dataclass
class TogglEntry:
    """An entry on Toggl."""

    name: str
    client: Optional[str] = None
    client_id: Optional[int] = None
    project: Optional[str] = None
    project_id: Optional[int] = None


class TogglMenuItem(MenuItem):
    """A Toggl menu item."""

    entry: TogglEntry
    updated: bool = True


class TogglPlugin(BasePlugin):
    """Toggl plugin."""

    toggl = Toggl()
    entries: Dict[str, TogglEntry] = {}
    menu_items: Dict[str, TogglMenuItem] = {}

    @property
    def name(self) -> str:
        """Plugin name."""
        return "Toggl"

    def init_app(self, app: DontForgetApp) -> bool:
        """Init the plugin."""
        self.app = app
        if not self.set_api_token():
            return False
        return self.create_menu()

    def set_api_token(self):
        """Set the API token to communicate with the Toggl API."""
        api_token = keyring.get_password(self.name, KEYRING_API_TOKEN)
        if not api_token:
            message = (
                "The Toggl API token is not set on the keyring."
                f" Run this command and paste the token: keyring set {self.name} {KEYRING_API_TOKEN}"
            )
            logger.error(message)
            click.secho(message, fg="bright_red")
            return False
        self.toggl.setAPIKey(api_token)
        return True

    def create_menu(self) -> bool:
        """Create menu items.

        Read items in reversed order because they will be added to the menu always after the main menu.
        """
        self.fetch_entries()

        for entry in self.entries.values():  # type: TogglEntry
            menu_key = f"{entry.name} ({entry.client}/{entry.project})"
            menuitem = TogglMenuItem(menu_key, callback=self.entry_clicked)
            menuitem.entry = entry
            menuitem.updated = True
            self.app.menu.insert_after(self.name, menuitem)
            self.menu_items[menu_key] = menuitem
        return True

    @my_vcr.use_cassette(path=str(Path(DEFAULT_DIRS.user_cache_dir) / "toggl_entries.yaml"))
    def fetch_entries(self) -> Dict[str, TogglEntry]:
        """Fetch client and projects from Toggl entries."""
        self.entries = {}
        for data in reversed(self.plugin_config):
            entry = TogglEntry(**data)
            logger.debug("Fetching client/project for Toggl entry: %s", entry)

            # TODO: this method is completely not optimized; it makes lots of requests and there is no cache
            project_data = self.toggl.getClientProject(entry.client, entry.project)
            entry.project_id = project_data["data"]["id"]
            entry.client_id = project_data["data"]["cid"]
            self.entries[entry.name] = entry
        return self.entries

    def reload_config(self) -> bool:
        """Replace menus when the configuration is reloaded."""
        for menu in self.menu_items.values():
            menu.updated = False

        rv = self.create_menu()

        # Remove menu items that were not updated
        old_menus = self.menu_items.copy()
        self.menu_items.clear()
        for key, menu in old_menus.items():
            if menu.updated:
                self.menu_items[key] = menu
            else:
                del self.app.menu[key]

        return rv

    def entry_clicked(self, menu: TogglMenuItem):
        """Callback executed when a menu entry is clicked."""
        self.track_entry(menu.entry)

    @classmethod
    def register_cli_commands(cls):
        """Register CLI commands for this plugin."""
        return [track, what_i_did]

    def track_entry(self, entry: TogglEntry, echo=False):
        """Track an entry on Toggl."""
        msg = f"Starting Toggl entry: {entry.name}"
        if echo:
            click.echo(msg)
        logger.debug(msg)
        self.toggl.startTimeEntry(entry.name, self.entries[entry.name].project_id)


@click.command()
@click.argument("entry", nargs=-1)
def track(entry):
    """Track your work with Toggl."""
    joined_text = "".join(entry).strip().lower()

    config_yaml = load_config_file()
    plugin = TogglPlugin(config_yaml)
    if not plugin.set_api_token():
        raise ClickException("Failed to set API token")

    entries = plugin.fetch_entries()
    chosen = fzf(list(entries.keys()), query=joined_text)
    if not chosen:
        raise ClickException("No entry chosen")

    entry = plugin.entries[chosen]
    plugin.track_entry(entry, True)


@click.command()
@click.argument("date", nargs=1)
@click.argument("report", nargs=1)
def what_i_did(date, report):
    """Display a report of Toggl entries since the date."""
    click.echo(maya.when(date).date)
    click.echo(report)
