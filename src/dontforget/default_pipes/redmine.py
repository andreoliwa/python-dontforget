"""Redmine."""
from typing import Iterator

from redminelib import Redmine

from dontforget.pipes import BaseSource
from dontforget.typedefs import JsonDict


class RedmineSource(BaseSource):
    """Redmine source."""

    def pull(self, connection_info: JsonDict) -> Iterator[JsonDict]:
        """Pull issues from Redmine."""
        redmine = Redmine(connection_info["url"], key=connection_info["api_token"], raise_attr_exception=False)
        project = redmine.project.get(connection_info["project_id"])
        for item in project.issues.values("id", "subject", "due_date", "parent", "assigned_to"):
            # Skip issues without a due date
            if not item["due_date"]:
                continue

            if "parent" not in item:
                item["parent"] = None
            if "assigned_to" not in item:
                item["assigned_to"] = None

            # Escape double quotes in the subject
            if "subject" in item:
                item["subject"] = item["subject"].replace('"', '\\"')

            yield item
