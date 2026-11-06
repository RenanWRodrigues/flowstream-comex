"""Testes das regras puras de qualidade: parse dos artefatos do dbt e anomalias de volume."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from flowstream.quality.domain import (
    DqResult,
    QualityResultsError,
    detect_volume_anomalies,
    parse_run_results,
    parse_sources,
    summarize,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dbt"
TODAY = date(2026, 11, 3)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ run_results.json


def test_successful_build_is_parsed_by_resource_type() -> None:
    results = parse_run_results(fixture("run_results_sucesso.json"))

    kinds = sorted(r.tipo for r in results)
    assert kinds == ["model", "seed", "snapshot", "test", "test", "test"]  # exposure fica de fora
    assert {r.status for r in results} == {"success", "pass"}
    assert all(r.duracao_s >= 0 for r in results)
    model = next(r for r in results if r.tipo == "model")
    assert model.recurso == "model.flowstream.stg_equipamentos"
    assert model.nome == "stg_equipamentos"


def test_failed_and_warned_tests_keep_failing_rows() -> None:
    results = parse_run_results(fixture("run_results_falha.json"))

    failed = [r for r in results if r.status == "fail"]
    warned = [r for r in results if r.status == "warn"]
    assert [r.linhas_com_falha for r in failed] == [3]
    assert [r.linhas_com_falha for r in warned] == [2]
    assert failed[0].mensagem is not None and "3 results" in failed[0].mensagem


def test_compilation_error_is_recorded_with_message() -> None:
    results = parse_run_results(fixture("run_results_erro_compilacao.json"))

    errors = [r for r in results if r.status == "error"]
    assert len(errors) == 1
    assert errors[0].tipo == "model"
    assert errors[0].mensagem is not None and "Compilation Error" in errors[0].mensagem
    assert {r.status for r in results if r.tipo == "test"} == {"skipped"}


def test_messages_are_masked_and_truncated() -> None:
    body = fixture("run_results_falha.json").replace(
        "Got 3 results", "Cliente 12.ABC.345/01DE-35 " + "x" * 2000 + " Got 3 results"
    )

    failed = next(r for r in parse_run_results(body) if r.status == "fail")

    assert failed.mensagem is not None
    assert "12.ABC.345/01DE-35" not in failed.mensagem
    assert len(failed.mensagem) <= 500


@pytest.mark.parametrize("bad", ["", "não é json", '{"sem": "results"}', '{"results": [{}]}'])
def test_invalid_run_results_raise_clear_error(bad: str) -> None:
    with pytest.raises(QualityResultsError):
        parse_run_results(bad)


# ------------------------------------------------------------------ sources.json (freshness)


def test_fresh_sources_pass() -> None:
    results = parse_sources(fixture("sources.json"))

    assert {r.nome for r in results} == {"bronze.ptax", "bronze.comexstat"}
    assert {r.tipo for r in results} == {"freshness"}
    assert {r.status for r in results} == {"pass"}
    assert all(r.mensagem is not None and "h" in r.mensagem for r in results)


def test_late_sources_warn_or_error() -> None:
    results = {r.nome: r for r in parse_sources(fixture("sources_atrasada.json"))}

    assert results["bronze.ptax"].status == "warn"
    assert results["bronze.comexstat"].status == "error"
    assert "70,0 dias" in (results["bronze.comexstat"].mensagem or "")


def test_invalid_sources_raise_clear_error() -> None:
    with pytest.raises(QualityResultsError):
        parse_sources("[]")


# ------------------------------------------------------------------ resumo


def test_summary_of_a_clean_run_is_ok() -> None:
    results = parse_run_results(fixture("run_results_sucesso.json")) + parse_sources(
        fixture("sources.json")
    )

    summary = summarize(results, anomalies=[])

    assert summary.ok
    assert (summary.testes_ok, summary.testes_falha, summary.testes_aviso) == (3, 0, 0)
    assert summary.fontes_atrasadas == 0


def test_summary_flags_failures_errors_and_late_sources() -> None:
    results = (
        parse_run_results(fixture("run_results_falha.json"))
        + parse_run_results(fixture("run_results_erro_compilacao.json"))
        + parse_sources(fixture("sources_atrasada.json"))
    )

    summary = summarize(results, anomalies=[])

    assert not summary.ok
    assert summary.testes_falha == 1
    assert summary.testes_aviso == 1
    assert summary.recursos_com_erro == 1
    assert summary.fontes_atrasadas == 2


def test_warnings_alone_do_not_fail_the_run() -> None:
    warn = DqResult(tipo="test", recurso="test.x", nome="x", status="warn", duracao_s=Decimal(0))

    assert summarize([warn], anomalies=[]).ok


# ------------------------------------------------------------------ anomalias de volume


def history(rows: int, days: int = 14) -> dict[date, int]:
    return {TODAY - timedelta(days=d): rows for d in range(1, days + 1)}


def test_volume_in_line_with_history_is_not_an_anomaly() -> None:
    volumes = {"bronze.ptax": {**history(100), TODAY: 120}}

    assert detect_volume_anomalies(volumes, TODAY) == []


def test_volume_well_above_history_is_flagged_up() -> None:
    volumes = {"bronze.comexstat": {**history(1000), TODAY: 1800}}

    (anomaly,) = detect_volume_anomalies(volumes, TODAY)

    assert anomaly.tabela == "bronze.comexstat"
    assert anomaly.direcao == "ACIMA"
    assert anomaly.linhas_no_dia == 1800
    assert anomaly.media_14_dias == Decimal("1000.00")
    assert anomaly.desvio_pct == Decimal("0.8000")


def test_volume_well_below_history_is_flagged_down() -> None:
    volumes = {"bronze.ptax": {**history(100), TODAY: 40}}

    (anomaly,) = detect_volume_anomalies(volumes, TODAY)

    assert anomaly.direcao == "ABAIXO"
    assert anomaly.desvio_pct == Decimal("-0.6000")


def test_exactly_fifty_percent_is_not_an_anomaly() -> None:
    volumes = {"bronze.ptax": {**history(100), TODAY: 150}}

    assert detect_volume_anomalies(volumes, TODAY) == []


def test_only_the_last_14_days_count() -> None:
    old = {TODAY - timedelta(days=d): 10_000 for d in range(15, 40)}
    volumes = {"bronze.ptax": {**old, **history(100), TODAY: 110}}

    assert detect_volume_anomalies(volumes, TODAY) == []


def test_mean_uses_only_days_with_load() -> None:
    sparse = {TODAY - timedelta(days=7): 1000, TODAY - timedelta(days=2): 1000}
    volumes = {"bronze.comexstat": {**sparse, TODAY: 1000}}

    assert detect_volume_anomalies(volumes, TODAY) == []


def test_without_history_or_without_load_today_there_is_nothing_to_compare() -> None:
    volumes = {
        "bronze.nova": {TODAY: 500},  # primeira carga: sem histórico
        "bronze.ptax": history(100),  # sem carga hoje (fim de semana): freshness cuida
    }

    assert detect_volume_anomalies(volumes, TODAY) == []


def test_tables_are_checked_independently_and_sorted() -> None:
    volumes = {
        "bronze.b": {**history(100), TODAY: 10},
        "bronze.a": {**history(100), TODAY: 300},
        "bronze.c": {**history(100), TODAY: 100},
    }

    assert [a.tabela for a in detect_volume_anomalies(volumes, TODAY)] == ["bronze.a", "bronze.b"]
