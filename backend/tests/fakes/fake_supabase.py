"""An in-memory stand-in for the supabase-py client, used only in tests. No network
calls, no real Supabase project — this exists so the Supabase-branch logic in the
repositories (translation, dedup, duplicate-key handling) can be unit tested without
touching a live database.

It intentionally mimics just enough of the real client's behavior (verified against
the installed supabase-py/postgrest version during the live audit) to exercise that
logic: chained .table().select().eq().limit().execute(), .insert(), .upsert() with
on_conflict/ignore_duplicates, and .delete().
"""

from contextlib import ExitStack
from unittest.mock import patch

from postgrest import APIError

UNIQUE_VIOLATION = "23505"


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeTableQuery:
    def __init__(self, client: "FakeSupabaseClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self._filters: dict = {}
        self._pending = ("select",)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._filters[column] = ("eq", value)
        return self

    def in_(self, column, values):
        self._filters[column] = ("in", list(values))
        return self

    def ilike(self, column, pattern):
        # Only supports the "%term%" substring form this codebase actually uses.
        term = pattern.strip("%").lower()
        self._filters[column] = ("ilike", term)
        return self

    def limit(self, _n):
        return self

    def insert(self, payload):
        self._pending = ("insert", payload)
        return self

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self._pending = ("upsert", payload, on_conflict, ignore_duplicates)
        return self

    def update(self, payload):
        self._pending = ("update", payload)
        return self

    def delete(self):
        self._pending = ("delete",)
        return self

    def execute(self):
        return self.client._execute(self.table_name, self._filters, self._pending)


class FakeRPCQuery:
    def __init__(self, client: "FakeSupabaseClient", fn_name: str, params: dict):
        self.client = client
        self.fn_name = fn_name
        self.params = params

    def execute(self):
        self.client.rpc_calls.append((self.fn_name, dict(self.params)))
        result = self.client.rpc_results.get(self.fn_name, [])
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


class FakeSupabaseClient:
    """`tables` is a plain dict[str, list[dict]] the test can pre-populate directly.
    `raise_on_insert[table_name]` lets a test force the next insert into that table
    to raise, simulating a lost race against a concurrent writer.

    `rpc_results[fn_name]` is either a list of row-dicts to return, or an Exception
    (e.g. a postgrest.APIError) to raise on `.execute()` - lets a test simulate the
    match_document_chunks RPC's own input-validation guards without a live database.
    `rpc_calls` records every (fn_name, params) call for assertion."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.raise_on_insert: dict[str, Exception] = {}
        self.rpc_results: dict[str, list[dict] | Exception] = {}
        self.rpc_calls: list[tuple[str, dict]] = []

    def table(self, name: str) -> FakeTableQuery:
        return FakeTableQuery(self, name)

    def rpc(self, fn_name: str, params: dict) -> FakeRPCQuery:
        return FakeRPCQuery(self, fn_name, params)

    @staticmethod
    def _row_matches(row: dict, filters: dict) -> bool:
        for column, spec in filters.items():
            op, value = spec
            if op == "eq":
                if row.get(column) != value:
                    return False
            elif op == "in":
                if row.get(column) not in value:
                    return False
            elif op == "ilike":
                if value not in str(row.get(column, "")).lower():
                    return False
        return True

    def _execute(self, table_name, filters, pending):
        rows = self.tables.setdefault(table_name, [])
        kind = pending[0]

        if kind == "update":
            payload = pending[1]
            matched = [r for r in rows if self._row_matches(r, filters)]
            for r in matched:
                r.update(payload)
            return FakeResponse(matched)

        if kind == "insert":
            payload = pending[1]
            err = self.raise_on_insert.pop(table_name, None)
            if err is not None:
                raise err
            payload_list = payload if isinstance(payload, list) else [payload]
            for p in payload_list:
                rows.append(dict(p))
            return FakeResponse(payload_list)

        if kind == "upsert":
            payload, on_conflict, ignore_duplicates = pending[1], pending[2], pending[3]
            key_cols = [c.strip() for c in (on_conflict or "").split(",") if c.strip()]
            existing_idx = next(
                (i for i, r in enumerate(rows) if key_cols and all(r.get(c) == payload.get(c) for c in key_cols)),
                None,
            )
            if existing_idx is not None:
                if not ignore_duplicates:
                    rows[existing_idx].update(payload)
                return FakeResponse([rows[existing_idx]])
            new_row = dict(payload)
            new_row.setdefault("id", f"fake-id-{table_name}-{len(rows)}")
            rows.append(new_row)
            return FakeResponse([new_row])

        if kind == "delete":
            matched = [r for r in rows if self._row_matches(r, filters)]
            self.tables[table_name] = [r for r in rows if r not in matched]
            return FakeResponse(matched)

        # select
        matched = [r for r in rows if self._row_matches(r, filters)]
        return FakeResponse(matched)


def unique_violation(message: str = "duplicate key value violates unique constraint") -> APIError:
    return APIError({"message": message, "code": UNIQUE_VIOLATION, "hint": None, "details": None})


def patch_supabase_backend(client: FakeSupabaseClient) -> ExitStack:
    """Patches every module that talks to Supabase so the given fake client is used
    instead of a real one, and so storage_backend_name() resolves to "supabase" for
    the three repositories. Returns an ExitStack the caller enters as a context
    manager (`with patch_supabase_backend(client):`)."""
    stack = ExitStack()
    targets = [
        ("app.repositories.announcements", True),
        ("app.repositories.financial_metrics", True),
        ("app.repositories.alerts", True),
        ("app.repositories.company_lookup", False),
        ("app.repositories.app_user", False),
        ("app.services.retrieval", True),
        ("app.repositories.documents", True),
    ]
    for module_path, patch_backend_name in targets:
        stack.enter_context(patch(f"{module_path}.get_supabase_client", return_value=client))
        if patch_backend_name:
            stack.enter_context(patch(f"{module_path}.storage_backend_name", return_value="supabase"))
    return stack
