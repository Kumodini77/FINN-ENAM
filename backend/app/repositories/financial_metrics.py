import logging

from app.core.config import get_settings
from app.core.db import get_supabase_client, storage_backend_name
from app.models.announcement import FinancialBasis, FinancialMetric
from app.repositories.company_lookup import get_company_id, get_or_register_company_id, get_ticker
from app.repositories.json_store import JsonListStore

logger = logging.getLogger("finn.repositories.financial_metrics")


def _basis_value(basis) -> str:
    """Normalizes a FinancialBasis enum or plain string to the plain string value
    PostgREST's query-string filters need — passing the enum object directly would
    serialize via its default repr, not its .value."""
    return basis.value if isinstance(basis, FinancialBasis) else basis


def _to_db_payload(metric: FinancialMetric, company_id: str) -> dict:
    payload = metric.model_dump(mode="json")
    payload.pop("company_ticker", None)
    payload["company_id"] = company_id
    return payload


def _from_db_row(row: dict) -> FinancialMetric:
    data = dict(row)
    data["company_ticker"] = get_ticker(row["company_id"]) or row["company_id"]
    return FinancialMetric.model_validate(data)


class FinancialMetricRepository:
    def __init__(self, store: JsonListStore | None = None):
        settings = get_settings()
        # See AnnouncementRepository's identical note: an explicitly-injected store
        # forces JSON-fallback isolation, regardless of what's configured globally.
        self._force_json = store is not None
        self._store = store or JsonListStore(settings.data_dir, "financial_metrics.json")

    def _backend(self) -> str:
        if self._force_json:
            return "json_fallback"
        return storage_backend_name()

    def find_existing(self, company_ticker: str, period: str, basis: str) -> FinancialMetric | None:
        if self._backend() == "supabase":
            company_id = get_company_id(company_ticker)
            if company_id is None:
                return None
            client = get_supabase_client()
            resp = (
                client.table("financial_metrics")
                .select("*")
                .eq("company_id", company_id)
                .eq("period", period)
                .eq("basis", _basis_value(basis))
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return _from_db_row(rows[0]) if rows else None

        for row in self._store.read_all():
            if row.get("company_ticker") == company_ticker and row.get("period") == period and row.get("basis") == basis:
                return FinancialMetric.model_validate(row)
        return None

    def upsert(self, metric: FinancialMetric) -> tuple[FinancialMetric, bool]:
        """Returns (record, created). A matching (ticker, period, basis) is replaced,
        not duplicated — re-importing a correction for the same quarter is expected."""
        existing = self.find_existing(metric.company_ticker, metric.period, metric.basis)
        created = existing is None

        if self._backend() == "supabase":
            company_id = get_or_register_company_id(metric.company_ticker)
            client = get_supabase_client()
            payload = _to_db_payload(metric, company_id)
            client.table("financial_metrics").upsert(payload, on_conflict="company_id,period,basis").execute()
        else:
            records = self._store.read_all()
            records = [
                r
                for r in records
                if not (r.get("company_ticker") == metric.company_ticker and r.get("period") == metric.period and r.get("basis") == metric.basis)
            ]
            records.append(metric.model_dump(mode="json"))
            self._store.replace_all(records)

        return metric, created

    def list_for_ticker(self, company_ticker: str, basis: str | None = None) -> list[FinancialMetric]:
        if self._backend() == "supabase":
            company_id = get_company_id(company_ticker)
            if company_id is None:
                return []
            client = get_supabase_client()
            query = client.table("financial_metrics").select("*").eq("company_id", company_id)
            if basis:
                query = query.eq("basis", _basis_value(basis))
            resp = query.execute()
            return [_from_db_row(r) for r in (resp.data or [])]

        rows = [r for r in self._store.read_all() if r.get("company_ticker") == company_ticker]
        if basis:
            rows = [r for r in rows if r.get("basis") == basis]
        return [FinancialMetric.model_validate(r) for r in rows]
