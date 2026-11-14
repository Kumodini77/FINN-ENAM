import logging
from datetime import date, datetime, timezone

from postgrest import APIError

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.models.announcement import Alert, AlertsConfig
from app.repositories.app_user import get_app_user_id
from app.repositories.company_lookup import get_company_id, get_or_register_company_id, get_ticker
from app.repositories.json_store import JsonListStore

logger = logging.getLogger("finn.repositories.alerts")

_UNIQUE_VIOLATION = "23505"


def _to_db_payload(alert: Alert, company_id: str, user_id: str) -> dict:
    payload = alert.model_dump(mode="json")
    payload.pop("company_ticker", None)
    payload["company_id"] = company_id
    payload["user_id"] = user_id
    return payload


def _from_db_row(row: dict) -> Alert:
    data = dict(row)
    data["company_ticker"] = get_ticker(row["company_id"]) or row["company_id"]
    return Alert.model_validate(data)


class AlertRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        # See AnnouncementRepository's identical note: an explicitly-injected store
        # forces JSON-fallback isolation, regardless of what's configured globally.
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "alerts.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def _read_rows(self, company_id: str | None = None) -> list[dict]:
        """Scoped to the single demo user's own alerts (requirements.md Module 8 —
        alerts belong to a user, even though there's only one today). For Supabase,
        narrowing to company_id too (when given) avoids pulling every alert just to
        check one company's dedup state."""
        if self._backend() == "supabase":
            client = get_supabase_client()
            user_id = get_app_user_id()
            query = client.table("alerts").select("*").eq("user_id", user_id)
            if company_id is not None:
                query = query.eq("company_id", company_id)
            resp = query.execute()
            return resp.data or []
        return self._store.read_all()

    def exists(self, company_ticker: str, trigger_type: str, trade_date: date | None, source_announcement_id: str | None) -> bool:
        """Dedup key per requirements.md Module 6/8: same user + same company + same
        trigger type + same trading date (for market alerts) OR same source
        announcement (for material-announcement alerts) must never fire twice."""
        if self._backend() == "supabase":
            company_id = get_company_id(company_ticker)
            if company_id is None:
                return False  # never registered -> no alert could exist for it yet
            rows = self._read_rows(company_id)
        else:
            rows = [r for r in self._store.read_all() if r.get("company_ticker") == company_ticker]

        for row in rows:
            if row.get("trigger_type") != trigger_type:
                continue
            if trigger_type == "material_announcement":
                if row.get("source_announcement_id") == source_announcement_id:
                    return True
            else:
                row_date = row.get("trade_date")
                if row_date == (trade_date.isoformat() if trade_date else None):
                    return True
        return False

    def add(self, alert: Alert) -> tuple[Alert, bool]:
        if self.exists(alert.company_ticker, alert.trigger_type.value, alert.trade_date, alert.source_announcement_id):
            return alert, False

        if self._backend() == "supabase":
            company_id = get_or_register_company_id(alert.company_ticker)
            user_id = get_app_user_id()
            client = get_supabase_client()
            payload = _to_db_payload(alert, company_id, user_id)
            try:
                client.table("alerts").insert(payload).execute()
            except APIError as e:
                if e.code == _UNIQUE_VIOLATION:
                    # Lost a race to a concurrent insert of the same dedup key —
                    # an idempotent duplicate result, not an unexplained 500.
                    return alert, False
                raise
        else:
            self._store.append(alert.model_dump(mode="json"))
        return alert, True

    def list_all(self) -> list[Alert]:
        if self._backend() == "supabase":
            return [_from_db_row(r) for r in self._read_rows()]
        return [Alert.model_validate(r) for r in self._store.read_all()]


class AlertsConfigRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        # See AnnouncementRepository's identical note: an explicitly-injected store
        # forces JSON-fallback isolation, regardless of what's configured globally.
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "alerts_config.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def get(self, user_id: str = "default") -> AlertsConfig:
        """The public contract keeps `user_id` as the app-level label ("default") —
        the real Supabase uuid is resolved underneath and translated back, so the
        API/schema layer never needs to know a real user_id exists."""
        settings = get_settings()
        if self._backend() == "supabase":
            client = get_supabase_client()
            real_user_id = get_app_user_id()
            resp = client.table("alerts_config").select("*").eq("user_id", real_user_id).limit(1).execute()
            rows = resp.data or []
            if rows:
                data = dict(rows[0])
                data["user_id"] = user_id
                return AlertsConfig.model_validate(data)
        else:
            for row in self._store.read_all():
                if row.get("user_id") == user_id:
                    return AlertsConfig.model_validate(row)

        return AlertsConfig(
            user_id=user_id,
            volume_spike_multiple=settings.default_volume_spike_multiple,
            price_move_pct=settings.default_price_move_pct,
            digest_window_hours=settings.default_digest_window_hours,
            updated_at=datetime.now(timezone.utc),
        )

    def save(self, config: AlertsConfig) -> AlertsConfig:
        config.updated_at = datetime.now(timezone.utc)
        if self._backend() == "supabase":
            client = get_supabase_client()
            real_user_id = get_app_user_id()
            payload = config.model_dump(mode="json")
            payload["user_id"] = real_user_id
            client.table("alerts_config").upsert(payload, on_conflict="user_id").execute()
        else:
            records = [r for r in self._store.read_all() if r.get("user_id") != config.user_id]
            records.append(config.model_dump(mode="json"))
            self._store.replace_all(records)
        return config
